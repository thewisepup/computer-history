import Foundation

/// Appends window text records to the spool one at a time, counting each failed write.
final class RecordWriter: Sendable {
    private let spool: any SpoolAppender
    private let counts: CaptureCounts
    private let lock = NSLock()

    init(spool: any SpoolAppender, counts: CaptureCounts) {
        self.spool = spool
        self.counts = counts
    }

    /// Appends the record if the check, made while no other record is being written, allows it, and returns whether it was written.
    @discardableResult
    func write(_ record: SpoolRecord, if allowed: () -> Bool = { true }) -> Bool {
        lock.withLock {
            guard allowed() else { return false }
            do {
                try spool.append(record)
                return true
            } catch {
                counts.recordFailed(error)
                return false
            }
        }
    }
}
