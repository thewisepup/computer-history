import Foundation

/// Counts what the capture thread read, wrote and excluded since the last summary, for the once-a-minute log line.
public final class CaptureCounts: @unchecked Sendable {
    public struct Summary: Equatable, Sendable, CustomStringConvertible {
        public var written = 0
        public var excluded = 0
        public var timedOut = 0
        public var cutOff = 0
        public var failed = 0
        public var slowestRead: TimeInterval = 0
        public var lastError: String?

        public var description: String {
            var line = "\(written) captures written, \(excluded) excluded, \(timedOut) timed out, \(cutOff) cut off, "
                + "slowest read \(String(format: "%.2f", slowestRead))s"
            if failed > 0 { line += ", \(failed) failed to write (last: \(lastError ?? "unknown"))" }
            return line
        }
    }

    private let lock = NSLock()
    private var current = Summary()

    public init() {}

    /// Returns the counts since the last call and starts again from zero.
    public func take() -> Summary {
        lock.withLock {
            defer { current = Summary() }
            return current
        }
    }

    func recordRead(seconds: TimeInterval) {
        lock.withLock { current.slowestRead = max(current.slowestRead, seconds) }
    }

    func recordWritten(_ window: WindowText) {
        lock.withLock {
            current.written += 1
            if window.timedOut { current.timedOut += 1 }
            if window.cutOff { current.cutOff += 1 }
        }
    }

    func recordExcluded() {
        lock.withLock { current.excluded += 1 }
    }

    func recordFailed(_ error: any Error) {
        lock.withLock {
            current.failed += 1
            current.lastError = String(describing: error)
        }
    }
}
