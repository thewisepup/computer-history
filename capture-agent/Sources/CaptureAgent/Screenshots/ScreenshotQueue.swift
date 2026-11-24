import Foundation

/// The recognized text of a kept screenshot, set on the screenshot thread once its recognition has run, or marked failed.
final class KeptText: @unchecked Sendable {
    private let lock = NSLock()
    private var state = KeptTextState.pending

    /// Whether reading the kept image's text failed or got no answer in time.
    var failed: Bool { lock.withLock { state == .failed } }

    fileprivate var value: (text: String, fullTextBytes: Int) {
        lock.withLock {
            switch state {
            case .pending, .failed: ("", 0)
            case .read(let text, let fullTextBytes): (text, fullTextBytes)
            }
        }
    }

    fileprivate func set(_ text: String, fullTextBytes: Int, log: AgentLog) {
        _ = lock.withLock { state.handle(.recognized(text, fullTextBytes: fullTextBytes), log: log, .ocr) }
    }

    fileprivate func fail(log: AgentLog) {
        _ = lock.withLock { state.handle(.recognitionFailed, log: log, .ocr) }
    }
}

/// A kept screenshot's text: not read yet, read, or failed to read.
enum KeptTextState: StateMachine {
    enum Event {
        case recognized(String, fullTextBytes: Int)
        case recognitionFailed
    }

    static let name = "kept text"

    case pending
    case read(text: String, fullTextBytes: Int)
    case failed

    func after(_ event: Event) -> KeptTextState? {
        switch (self, event) {
        case (.pending, .recognized(let text, let fullTextBytes)):
            .read(text: text, fullTextBytes: fullTextBytes)
        case (.pending, .recognitionFailed):
            .failed
        case (.read, .recognized), (.read, .recognitionFailed), (.failed, .recognized), (.failed, .recognitionFailed):
            nil
        }
    }
}

/// Text recognition that gave no answer in time, or was not started because an earlier one still has not answered.
struct RecognitionUnanswered: Error, CustomStringConvertible {
    let timeout: TimeInterval
    var description: String { "no text recognized within \(timeout)s, or an earlier recognition is still running" }
}

/// Writes screenshot records to the spool on its own thread in the order they were added, reading the text in each kept image first.
final class ScreenshotQueue: Sendable {
    private let queue = DispatchQueue(label: "screenshots", qos: .utility, autoreleaseFrequency: .workItem)
    private let recognition = DispatchQueue(label: "recognition", qos: .utility, autoreleaseFrequency: .workItem)
    private let recognize: @Sendable (URL) throws -> String
    private let recognitions: OneRequestAtATime
    private let capBytes: Int
    private let timeout: TimeInterval
    private let spool: any SpoolAppender
    private let counts: CaptureCounts
    private let log: AgentLog
    private let state = QueueState()

    init(
        recognize: @escaping @Sendable (URL) throws -> String, capBytes: Int, timeout: TimeInterval, spool: any SpoolAppender,
        counts: CaptureCounts, log: AgentLog
    ) {
        self.recognize = recognize
        self.capBytes = capBytes
        self.timeout = timeout
        self.spool = spool
        self.counts = counts
        self.log = log
        recognitions = OneRequestAtATime(log: log, .ocr)
    }

    func add(_ screenshot: QueuedScreenshot) {
        counts.recordScreenshotsQueued(state.added())
        queue.async {
            let record = self.finished(screenshot)
            self.counts.recordScreenshotsQueued(self.state.done { self.write(record) })
        }
    }

    /// Waits until every screenshot added so far has been written or refused.
    func waitUntilWritten() {
        queue.sync {}
    }

    /// Waits until the deadline at most for the screenshots added so far, then writes no more, and returns how many were left unwritten.
    func stop(by deadline: DispatchTime) -> Int {
        let drained = DispatchSemaphore(value: 0)
        queue.async { drained.signal() }
        _ = drained.wait(timeout: deadline)
        return state.close()
    }

    private func finished(_ screenshot: QueuedScreenshot) -> ScreenshotRecord {
        switch screenshot {
        case .ready(let record):
            return record
        case .copy(let kept, let record):
            return record(kept.value)
        case .recognize(let image, let kept, let record):
            do {
                var capped = CappedText(capBytes: capBytes)
                capped.append(try recognizeInTime(image))
                kept.set(capped.text, fullTextBytes: capped.fullLength, log: log)
            } catch {
                kept.fail(log: log)
                counts.recordRecognitionFailed(error)
                log.debug(.ocr, "text recognition failed for \(image.lastPathComponent): \(error)")
            }
            return record(kept.value)
        }
    }

    private func recognizeInTime(_ image: URL) throws -> String {
        let unanswered = Result<String, any Error>.failure(RecognitionUnanswered(timeout: timeout))
        return try recognitions.run(timeout: timeout, otherwise: unanswered) { answer in
            recognition.async { [recognize] in answer(Result { try recognize(image) }) }
        }.get()
    }

    private func write(_ record: ScreenshotRecord) {
        do {
            try spool.append(record)
        } catch {
            counts.recordScreenshotFailed(error)
        }
    }
}

private final class QueueState: @unchecked Sendable {
    private let lock = NSLock()
    private var pending = 0
    private var closed = false

    func added() -> Int {
        lock.withLock {
            pending += 1
            return pending
        }
    }

    func done(_ write: () -> Void) -> Int {
        lock.withLock {
            if !closed { write() }
            pending -= 1
            return pending
        }
    }

    func close() -> Int {
        lock.withLock {
            closed = true
            return pending
        }
    }
}
