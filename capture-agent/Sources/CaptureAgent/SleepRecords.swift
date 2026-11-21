import Foundation

/// Writes a slept record as the Mac goes to sleep and a woke record as it wakes from a sleep it recorded; nothing while capture is paused.
final class SleepRecords: @unchecked Sendable {
    private let spool: any SpoolAppender
    private let pause: PauseSwitch
    private let counts: CaptureCounts
    private let lock = NSLock()
    private var recordedSleep = false

    init(spool: any SpoolAppender, pause: PauseSwitch, counts: CaptureCounts) {
        self.spool = spool
        self.pause = pause
        self.counts = counts
    }

    func receive(_ change: SleepChange, at time: Date) {
        lock.withLock {
            switch change {
            case .willSleep:
                guard !pause.isPaused else { return }
                recordedSleep = write(.slept(at: time))
            case .didWake:
                guard recordedSleep else { return }
                recordedSleep = false
                _ = write(.woke(at: time))
            }
        }
    }

    private func write(_ record: SpoolRecord) -> Bool {
        do {
            try spool.append(record)
            return true
        } catch {
            counts.recordFailed(error)
            return false
        }
    }
}
