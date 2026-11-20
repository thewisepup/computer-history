import Foundation

/// The recognized text of a kept screenshot, set on the screenshot thread once its recognition has run.
final class KeptText: @unchecked Sendable {
    fileprivate var text = ""
    fileprivate var fullTextBytes = 0
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
    private let recognitions = OneRequestAtATime()
    private let capBytes: Int
    private let timeout: TimeInterval
    private let spool: any SpoolAppender
    private let counts: CaptureCounts
    private let pending = Pending()

    init(
        recognize: @escaping @Sendable (URL) throws -> String, capBytes: Int, timeout: TimeInterval, spool: any SpoolAppender,
        counts: CaptureCounts
    ) {
        self.recognize = recognize
        self.capBytes = capBytes
        self.timeout = timeout
        self.spool = spool
        self.counts = counts
    }

    func add(_ screenshot: QueuedScreenshot) {
        counts.recordScreenshotsQueued(pending.add(1))
        queue.async {
            self.write(self.finished(screenshot))
            self.counts.recordScreenshotsQueued(self.pending.add(-1))
        }
    }

    /// Waits until every screenshot added so far has been written or refused.
    func waitUntilWritten() {
        queue.sync {}
    }

    private func finished(_ screenshot: QueuedScreenshot) -> ScreenshotRecord {
        switch screenshot {
        case .ready(let record):
            return record
        case .copy(let kept, let record):
            return record(kept.text, kept.fullTextBytes)
        case .recognize(let image, let kept, let record):
            do {
                var capped = CappedText(capBytes: capBytes)
                capped.append(try recognizeInTime(image))
                kept.text = capped.text
                kept.fullTextBytes = capped.fullLength
            } catch {
                counts.recordRecognitionFailed(error)
            }
            return record(kept.text, kept.fullTextBytes)
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

private final class Pending: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    func add(_ change: Int) -> Int {
        lock.withLock {
            count += change
            return count
        }
    }
}
