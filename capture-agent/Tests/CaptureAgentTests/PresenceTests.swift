import Foundation
import Testing
@testable import CaptureAgent

@Test func staysAsleepUntilInputArrivesAfterTheSleepNotification() {
    #expect(isStillAsleep(sleptAt: 100, idleSeconds: 30, uptime: 120))
    #expect(isStillAsleep(sleptAt: 100, idleSeconds: 20, uptime: 120))
    #expect(!isStillAsleep(sleptAt: 100, idleSeconds: 5, uptime: 120))
}

@MainActor
@Test func inputAfterARecordedSleepWritesItsWakeOnceAndStaysAsleepUntilThen() async {
    let logs = LogRecorder()
    let watch = SleepWatch(log: logs.log)
    let changes = SleepChanges(recording: true) { change in
        if change == .didWake { #expect(watch.stillAsleep(idleSeconds: 5, uptime: 121)) }
    }
    watch.onChange(changes.receive)
    watch.willSleep(at: 100, Date())
    #expect(watch.stillAsleep(idleSeconds: 30, uptime: 120))
    #expect(watch.current == .asleep(since: 100, recorded: true))
    #expect(watch.stillAsleep(idleSeconds: 5, uptime: 120))
    await drainMainQueue()
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

@Test func inputWhileTheSleptRecordIsWrittenStillGetsItsWake() {
    let logs = LogRecorder()
    let watch = SleepWatch(log: logs.log)
    let changes = SleepChanges(recording: true) { change in
        if change == .willSleep { #expect(!watch.stillAsleep(idleSeconds: 5, uptime: 120)) }
    }
    watch.onChange(changes.receive)
    watch.willSleep(at: 100, Date())
    #expect(changes.values == [.willSleep, .didWake])
    #expect(watch.current == .awake)
    #expect(logs.records.isEmpty)
}

@MainActor
@Test func aSleepBeforeAQueuedWakeIsWrittenWritesThatWakeFirstAndOnlyOnce() async {
    let logs = LogRecorder()
    let watch = SleepWatch(log: logs.log)
    let changes = SleepChanges(recording: true)
    watch.onChange(changes.receive)
    watch.willSleep(at: 100, Date())
    #expect(watch.stillAsleep(idleSeconds: 5, uptime: 120))
    watch.willSleep(at: 200, Date())
    await drainMainQueue()
    #expect(changes.values == [.willSleep, .didWake, .willSleep])
    #expect(watch.current == .asleep(since: 200, recorded: true))
    #expect(logs.records.isEmpty)
}

private func drainMainQueue() async {
    await withCheckedContinuation { done in DispatchQueue.main.async { done.resume() } }
}

private final class SleepChanges: @unchecked Sendable {
    let recording: Bool
    private let lock = NSLock()
    private var seen: [SleepChange] = []

    private let during: @Sendable (SleepChange) -> Void

    init(recording: Bool, during: @escaping @Sendable (SleepChange) -> Void = { _ in }) {
        self.recording = recording
        self.during = during
    }

    var values: [SleepChange] { lock.withLock { seen } }

    func receive(_ change: SleepChange, at _: Date) -> Bool {
        lock.withLock { seen.append(change) }
        during(change)
        return recording
    }
}
