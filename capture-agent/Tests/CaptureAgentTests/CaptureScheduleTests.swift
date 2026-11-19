import Foundation
import Testing
@testable import CaptureAgent

struct Capture: Equatable, CustomStringConvertible {
    let at: Double
    let trigger: SpoolRecord.Trigger

    init(_ at: Double, _ trigger: SpoolRecord.Trigger) {
        self.at = at
        self.trigger = trigger
    }

    var description: String { "\(trigger)@\(at)" }

    static func == (lhs: Capture, rhs: Capture) -> Bool {
        lhs.trigger == rhs.trigger && abs(lhs.at - rhs.at) < 1e-6
    }
}

func simulate(
    _ settings: CaptureSettings = CaptureSettings(),
    until end: Double,
    events: [(Double, CaptureSchedule.Event)] = []
) -> [Capture] {
    let stepMilliseconds = 50
    var schedule = CaptureSchedule(settings: settings, start: 0)
    var remaining = events.sorted { $0.0 < $1.0 }[...]
    var captures: [Capture] = []
    for millisecond in stride(from: 0, through: Int(end * 1000), by: stepMilliseconds) {
        let now = Double(millisecond) / 1000
        while let (at, event) = remaining.first, at <= now + 1e-9 {
            schedule.receive(event, at: at)
            remaining = remaining.dropFirst()
        }
        if let trigger = schedule.takeDue(at: now + 1e-6) {
            captures.append(Capture(now, trigger))
        }
    }
    return captures
}

func idle(_ seconds: Double) -> CaptureSchedule.Event {
    .presence(Presence(idleSeconds: seconds, locked: false, asleep: false))
}

@Test func heartbeatEveryThirtySecondsWhileActive() {
    #expect(simulate(until: 95) == [Capture(1, .heartbeat), Capture(31, .heartbeat), Capture(61, .heartbeat), Capture(91, .heartbeat)])
}

@Test func waitsTheSettleDelayAfterASwitch() {
    let captures = simulate(until: 15, events: [(10, .focusChanged(.app))])
    #expect(captures == [Capture(1, .heartbeat), Capture(11, .app)])
}

@Test func aBurstOfSwitchesYieldsOneCaptureOfTheFinalState() {
    let flips = stride(from: 10.0, through: 14.0, by: 0.3).map { ($0, CaptureSchedule.Event.focusChanged(.title)) }
    let captures = simulate(until: 20, events: flips + [(12, .focusChanged(.app))])
    #expect(captures == [Capture(1, .heartbeat), Capture(14.9, .app)])
}

@Test func neverTwoCapturesWithinASecondUnderRapidTabFlipping() {
    let settings = CaptureSettings(settleDelay: 0.2)
    let flips = stride(from: 5.0, through: 25.0, by: 0.3).map { ($0, CaptureSchedule.Event.focusChanged(.title)) }
    let captures = simulate(settings, until: 30, events: flips)
    let gaps = zip(captures.dropFirst(), captures).map { $0.at - $1.at }
    #expect(captures.count > 10)
    #expect(gaps.allSatisfy { $0 >= settings.minimumGap - 1e-9 })
}

@Test func slowSwitchesEachGetACaptureAtLeastASecondApart() {
    let switches = stride(from: 5.0, through: 15.0, by: 1.2).map { ($0, CaptureSchedule.Event.focusChanged(.window)) }
    let captures = simulate(until: 20, events: switches).filter { $0.trigger == .window }
    #expect(captures == stride(from: 6.0, through: 16.0, by: 1.2).map { Capture($0, .window) })
}

@Test func aSwitchResetsTheHeartbeatPhase() {
    let captures = simulate(until: 100, events: [(40, .focusChanged(.app))])
    #expect(captures == [Capture(1, .heartbeat), Capture(31, .heartbeat), Capture(41, .app), Capture(71, .heartbeat)])
}

@Test func aTitleThatNeverSettlesIsStillCapturedOnTheHeartbeat() {
    let flips = stride(from: 0.5, through: 70, by: 0.5).map { ($0, CaptureSchedule.Event.focusChanged(.title)) }
    let captures = simulate(until: 70, events: flips)
    #expect(captures == [Capture(30.5, .title), Capture(61, .title)])
}

@Test func silentWhileIdleAndResumesWithACaptureAfterTheSettleDelay() {
    let captures = simulate(until: 300, events: [
        (50, idle(181)),
        (60, .focusChanged(.app)),
        (200, idle(0)),
    ])
    #expect(captures == [Capture(1, .heartbeat), Capture(31, .heartbeat), Capture(201, .heartbeat), Capture(231, .heartbeat), Capture(261, .heartbeat), Capture(291, .heartbeat)])
}

@Test func idleIsOnlyAboveTheThreshold() {
    let threshold = CaptureSettings().idleThreshold
    var schedule = CaptureSchedule(settings: CaptureSettings(), start: 0)
    schedule.receive(idle(threshold), at: 0)
    #expect(schedule.silence.isEmpty)
    schedule.receive(idle(threshold + 0.5), at: 0)
    #expect(schedule.silence == [.idle])
}

@Test func silentWhileLockedAndDropsTheSwitchPendingAtTheLock() {
    let captures = simulate(until: 40, events: [
        (10, .focusChanged(.app)),
        (10.5, .presence(Presence(idleSeconds: 0, locked: true, asleep: false))),
        (20, .presence(present)),
    ])
    #expect(captures == [Capture(1, .heartbeat), Capture(21, .heartbeat)])
}

@Test func silentWhileAsleepAndResumesOnWake() {
    let captures = simulate(until: 70, events: [
        (5, .presence(Presence(idleSeconds: 0, locked: false, asleep: true))),
        (50, .presence(present)),
    ])
    #expect(captures == [Capture(1, .heartbeat), Capture(51, .heartbeat)])
}

@Test func staysSilentUntilEveryReasonClears() {
    var schedule = CaptureSchedule(settings: CaptureSettings(), start: 0)
    schedule.receive(.presence(Presence(idleSeconds: 500, locked: true, asleep: false)), at: 0)
    #expect(schedule.silence == [.idle, .locked])
    schedule.receive(.presence(Presence(idleSeconds: 500, locked: false, asleep: false)), at: 5)
    #expect(schedule.silence == [.idle])
    #expect(schedule.takeDue(at: 10) == nil)
    schedule.receive(.presence(present), at: 10)
    #expect(schedule.takeDue(at: 10.5) == nil)
    #expect(schedule.takeDue(at: 11) == .heartbeat)
}
