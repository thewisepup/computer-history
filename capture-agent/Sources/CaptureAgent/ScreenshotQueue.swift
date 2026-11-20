import Foundation

/// The recognized text of a kept screenshot, set on the screenshot thread once its recognition has run.
final class KeptText: @unchecked Sendable {
    fileprivate var text = ""
    fileprivate var fullTextBytes = 0
}

/// A screenshot record waiting for the spool: ready as it is, waiting on its own image's text, or copying a kept screenshot's text.
enum QueuedScreenshot: Sendable {
    case ready(ScreenshotRecord)
    case recognize(ScreenshotRecord, image: URL, into: KeptText)
    case copy(ScreenshotRecord, from: KeptText)
}

/// Writes screenshot records to the spool on its own thread in the order they were added, reading the text in each kept image first.
final class ScreenshotQueue: Sendable {
    private let queue = DispatchQueue(label: "screenshots", qos: .utility)
    private let recognize: @Sendable (URL) throws -> String
    private let capBytes: Int
    private let spool: any SpoolAppender
    private let counts: CaptureCounts

    init(recognize: @escaping @Sendable (URL) throws -> String, capBytes: Int, spool: any SpoolAppender, counts: CaptureCounts) {
        self.recognize = recognize
        self.capBytes = capBytes
        self.spool = spool
        self.counts = counts
    }

    func add(_ screenshot: QueuedScreenshot) {
        queue.async { self.write(self.finished(screenshot)) }
    }

    /// Waits until every screenshot added so far has been written or refused.
    func waitUntilWritten() {
        queue.sync {}
    }

    private func finished(_ screenshot: QueuedScreenshot) -> ScreenshotRecord {
        switch screenshot {
        case .ready(let record):
            return record
        case .copy(let record, let kept):
            return record.withText(kept.text, fullTextBytes: kept.fullTextBytes)
        case .recognize(let record, let image, let kept):
            do {
                var capped = CappedText(capBytes: capBytes)
                capped.append(try recognize(image))
                kept.text = capped.text
                kept.fullTextBytes = capped.fullLength
            } catch {
                counts.recordRecognitionFailed(error)
            }
            return record.withText(kept.text, fullTextBytes: kept.fullTextBytes)
        }
    }

    private func write(_ record: ScreenshotRecord) {
        do {
            try spool.append(record)
        } catch {
            counts.recordFailed(error, screenshot: true)
        }
    }
}
