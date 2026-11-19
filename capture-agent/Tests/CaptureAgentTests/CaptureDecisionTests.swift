import Foundation
import Testing
@testable import CaptureAgent

@Test func theDenylistMatchesBundleIDsIgnoringCase() {
    let denylist = Denylist(adding: ["Com.Example.Vault"])
    #expect(denylist.contains(FocusedApplication(
        processIdentifier: 1, bundleIdentifier: "com.example.vault", bundleURL: nil, name: "Vault"
    )))
    #expect(denylist.contains(onePassword))
    #expect(denylist.contains(FocusedApplication(
        processIdentifier: 1, bundleIdentifier: "com.apple.passwords", bundleURL: nil, name: "Passwords"
    )))
    #expect(!denylist.contains(plainApp))
    #expect(!denylist.contains(FocusedApplication(processIdentifier: 1, bundleIdentifier: nil, bundleURL: nil, name: "1Password")))
}

final class DecisionFixture {
    let focus = FocusFixture()
    var mac: ScriptedMac { focus.mac }
    var paused = false
    var recordsWrite = true
    var presence = present
    var time: TimeInterval = 0
    lazy var decision = CaptureDecision(
        settings: CaptureSettings(),
        denylist: Denylist(),
        paused: paused,
        apps: focus.appWatch,
        windows: focus.windowWatch,
        start: 0
    )

    func run(for seconds: TimeInterval) -> [TickOutcome] {
        var outcomes: [TickOutcome] = []
        let end = time + seconds
        while time < end {
            focus.mac.clock = time
            let outcome = decision.tick(paused: paused, presence: presence, accessibilityTrusted: { true }, at: time)
            if outcome != .nothing { outcomes.append(outcome) }
            if recordsWrite, outcome == .paused || outcome == .resumed { decision.recordedPause(outcome == .paused) }
            time += 0.5
        }
        return outcomes
    }
}

@Test func aDenylistedAppIsExcludedAndItsWindowNeverTouched() {
    let fixture = DecisionFixture()
    fixture.mac.focused = onePassword
    #expect(fixture.run(for: 31.5) == [.excluded(onePassword, .heartbeat), .excluded(onePassword, .heartbeat)])
    #expect(fixture.focus.passwordAppCalls().isEmpty)
    #expect(fixture.focus.mac.calls.isEmpty)
}

@Test func anAllowedAppIsCaptured() {
    let fixture = DecisionFixture()
    #expect(fixture.run(for: 2) == [.capture(plainApp, .heartbeat)])
    fixture.mac.focused = onePassword
    #expect(fixture.run(for: 2) == [.excluded(onePassword, .app)])
    fixture.mac.focused = chrome
    #expect(fixture.run(for: 2) == [.capture(chrome, .app)])
    #expect(fixture.focus.passwordAppCalls().isEmpty)
}

@Test func pauseAndResumeAreEachOneOutcomeWhateverThePresence() {
    let fixture = DecisionFixture()
    _ = fixture.decision
    fixture.paused = true
    #expect(fixture.run(for: 10) == [.paused])
    fixture.mac.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    #expect(fixture.run(for: 10).isEmpty)
    fixture.mac.presence = present
    #expect(fixture.run(for: 10).isEmpty)
    #expect(fixture.focus.mac.calls.isEmpty)
    #expect(fixture.decision.silence == [.paused])
    fixture.paused = false
    #expect(fixture.run(for: 2) == [.resumed, .capture(plainApp, .heartbeat)])
}

@Test func aDecisionStartedPausedReportsNoPauseOutcome() {
    let fixture = DecisionFixture()
    fixture.paused = true
    #expect(fixture.run(for: 60).isEmpty)
    #expect(fixture.decision.silence == [.paused])
    #expect(fixture.focus.mac.calls.isEmpty)
}

@Test func aPauseRecordThatFailedToWriteIsOfferedAgain() {
    let fixture = DecisionFixture()
    _ = fixture.decision
    fixture.paused = true
    fixture.recordsWrite = false
    #expect(fixture.run(for: 1) == [.paused, .paused])
    #expect(fixture.decision.silence == [.paused])
    fixture.recordsWrite = true
    #expect(fixture.run(for: 10) == [.paused])
    #expect(fixture.focus.mac.calls.isEmpty)
}
