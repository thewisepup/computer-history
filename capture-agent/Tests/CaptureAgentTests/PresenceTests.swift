import Foundation
import Testing
@testable import CaptureAgent

@Test func staysAsleepUntilInputArrivesAfterTheSleepNotification() {
    #expect(isStillAsleep(sleptAt: 100, idleSeconds: 30, uptime: 120))
    #expect(isStillAsleep(sleptAt: 100, idleSeconds: 20, uptime: 120))
    #expect(!isStillAsleep(sleptAt: 100, idleSeconds: 5, uptime: 120))
}

@Test func inputAfterARecordedSleepWritesItsWakeOnceAndStaysAsleepUntilThen() {
    let logs = LogRecorder()
    let watch = SleepWatch(log: logs.log)
    let changes = SleepChanges(recording: true)
    watch.onChange(changes.receive)
    watch.willSleep(at: 100, Date())
    #expect(watch.stillAsleep(idleSeconds: 30, uptime: 120))
    #expect(watch.current == .asleep(since: 100, recorded: true))
    #expect(watch.stillAsleep(idleSeconds: 5, uptime: 120))
    #expect(changes.woke.wait(timeout: .now() + 5) == .success)
    #expect(watch.current == .awake)
    #expect(!watch.stillAsleep(idleSeconds: 5, uptime: 121))
    watch.didWake(Date())
    #expect(changes.values == [.willSleep, .didWake])
    #expect(logs.records.isEmpty)
}

@Test func inputAfterAnUnrecordedSleepWakesAtOnceWithoutAWake() {
    let watch = SleepWatch(log: AgentLog { _ in })
    let changes = SleepChanges(recording: false)
    watch.onChange(changes.receive)
    watch.willSleep(at: 100, Date())
    #expect(!watch.stillAsleep(idleSeconds: 5, uptime: 120))
    #expect(watch.current == .awake)
    watch.didWake(Date())
    #expect(changes.values == [.willSleep])
}

private final class SleepChanges: @unchecked Sendable {
    let recording: Bool
    let woke = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var seen: [SleepChange] = []

    init(recording: Bool) { self.recording = recording }

    var values: [SleepChange] { lock.withLock { seen } }

    func receive(_ change: SleepChange, at _: Date) -> Bool {
        lock.withLock { seen.append(change) }
        if change == .didWake { woke.signal() }
        return recording
    }
}
