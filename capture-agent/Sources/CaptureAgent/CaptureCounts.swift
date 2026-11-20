import Foundation

/// Counts what the capture thread read, wrote and excluded since the last summary, for the once-a-minute log line.
public final class CaptureCounts: @unchecked Sendable {
    public struct Summary: Equatable, Sendable, CustomStringConvertible {
        public var written = 0
        public var excluded = 0
        public var timedOut = 0
        public var cutOff = 0
        public var failed = 0
        public var screenshotsFailed = 0
        public var recognitionsFailed = 0
        public var slowestRead: TimeInterval = 0
        public var screenshotsQueued = 0
        public var lastWriteError: String?
        public var lastScreenshotError: String?
        public var lastRecognitionError: String?

        public var description: String {
            let failures = [
                (failed, "failed to write", lastWriteError),
                (screenshotsFailed, "screenshot records failed to write", lastScreenshotError),
                (recognitionsFailed, "text recognitions failed", lastRecognitionError),
            ].filter { $0.0 > 0 }.map { ", \($0.0) \($0.1) (last: \($0.2 ?? "unknown"))" }
            return "\(written) captures written, \(excluded) excluded, \(timedOut) timed out, \(cutOff) cut off, "
                + "slowest read \(String(format: "%.2f", slowestRead))s, \(screenshotsQueued) screenshot records queued"
                + failures.joined()
        }
    }

    private let lock = NSLock()
    private var current = Summary()

    public init() {}

    /// Returns the counts since the last call and starts again from zero.
    public func take() -> Summary {
        lock.withLock {
            defer { current = Summary(screenshotsQueued: current.screenshotsQueued) }
            return current
        }
    }

    func recordRead(seconds: TimeInterval) {
        lock.withLock { current.slowestRead = max(current.slowestRead, seconds) }
    }

    func recordWritten(_ record: SpoolRecord) {
        lock.withLock {
            current.written += 1
            if record.timedOut == true { current.timedOut += 1 }
            if record.textCutOff == true { current.cutOff += 1 }
        }
    }

    func recordExcluded() {
        lock.withLock { current.excluded += 1 }
    }

    func recordRecognitionFailed(_ error: any Error) {
        lock.withLock {
            current.recognitionsFailed += 1
            current.lastRecognitionError = String(describing: error)
        }
    }

    func recordScreenshotsQueued(_ count: Int) {
        lock.withLock { current.screenshotsQueued = count }
    }

    func recordScreenshotFailed(_ error: any Error) {
        lock.withLock {
            current.screenshotsFailed += 1
            current.lastScreenshotError = String(describing: error)
        }
    }

    func recordFailed(_ error: any Error) {
        lock.withLock {
            current.failed += 1
            current.lastWriteError = String(describing: error)
        }
    }
}
