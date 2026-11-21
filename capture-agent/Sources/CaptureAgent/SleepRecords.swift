import Foundation

/// Writes a slept record as the Mac goes to sleep and a woke record as it wakes from a sleep it recorded; nothing while capture is paused.
final class SleepRecords: @unchecked Sendable {
    private let pause: PauseSwitch
    private let writer: RecordWriter
    private let lock = NSLock()
    private var recordedSleep = false

    init(pause: PauseSwitch, writer: RecordWriter) {
        self.pause = pause
        self.writer = writer
    }

    func receive(_ change: SleepChange, at time: Date) {
        lock.withLock {
            switch change {
            case .willSleep:
                guard !pause.isPaused else { return }
                recordedSleep = writer.write(.slept(at: time))
            case .didWake:
                guard recordedSleep else { return }
                recordedSleep = false
                writer.write(.woke(at: time))
            }
        }
    }
}
