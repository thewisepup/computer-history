import Foundation
import Testing
@testable import CaptureAgent

final class LoopFixture {
    let focus = FocusFixture()
    let spool = TempSpool()
    let counts = CaptureCounts()
    let pause: PauseSwitch
    var presence = present
    var trusted = true
    var windowText = WindowTextSettings()
    var denylist = Denylist()
    var logged: [String] = []
    private var nextTick: TimeInterval = 0
    private lazy var writer = spool.writer()

    var tree: FakeAccessibilityTree { focus.tree }

    init() {
        pause = PauseSwitch(file: spool.directory.appendingPathComponent("folder/\(AgentSettings.pauseFileName)"))
    }

    lazy var loop: CaptureLoop<FakeElement> = makeLoop()

    func makeLoop() -> CaptureLoop<FakeElement> {
        let reader = tree.reader(focus.apps, settings: windowText)
        return CaptureLoop(
            settings: CaptureSettings(),
            denylist: denylist,
            apps: focus.appWatch,
            windows: focus.windowWatch,
            isPaused: { self.pause.isPaused },
            presence: { self.presence },
            accessibilityTrusted: { self.trusted },
            read: reader.read,
            spool: writer,
            counts: counts,
            uptime: { self.tree.now },
            now: { self.spool.clock.now },
            log: { self.logged.append($0) }
        )
    }

    func restart() {
        loop = makeLoop()
    }

    func run(for seconds: TimeInterval) {
        let end = nextTick + seconds
        while nextTick < end {
            tree.now = max(tree.now, nextTick)
            loop.tick()
            nextTick += 0.5
        }
    }

    func records() throws -> [[String: Any]] {
        guard FileManager.default.fileExists(atPath: spool.directory.appendingPathComponent(SpoolWriter.openFileName).path) else {
            return []
        }
        return try spool.lines(SpoolWriter.openFileName).filter { !$0.isEmpty }.map {
            try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any]
        }
    }

    func triggers() throws -> [String] {
        try records().map { $0["trigger"] as! String }
    }

    func kinds() throws -> [String] {
        try records().map { $0["kind"] as! String }
    }
}

@Test func writesAHeartbeatCaptureOfTheFocusedWindow() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    let records = try fixture.records()
    #expect(records.count == 1)
    #expect(records[0]["kind"] as? String == "capture")
    #expect(records[0]["trigger"] as? String == "heartbeat")
    #expect(records[0]["app_name"] as? String == "TextEdit")
    #expect(records[0]["bundle_id"] as? String == "com.apple.TextEdit")
    #expect(records[0]["window_title"] as? String == "Notes")
    #expect(records[0]["text"] as? String == "hello")
    #expect(records[0]["captured_at"] as? String == "2026-11-18T09:00:00.000Z")
    #expect(fixture.counts.take().written == 1)
}

@Test func capturesAnAppSwitchAndATabSwitchOncePerSettledChange() throws {
    let fixture = LoopFixture()
    fixture.run(for: 10)
    fixture.focus.focused = chrome
    fixture.run(for: 5)
    fixture.focus.tab.attributes["AXTitle"] = "Pull requests"
    fixture.run(for: 5)
    let records = try fixture.records()
    #expect(try fixture.triggers() == ["heartbeat", "app", "title"])
    #expect(records[1]["app_name"] as? String == "Google Chrome")
    #expect(records[2]["window_title"] as? String == "Pull requests")
}

@Test func silenceMakesNoAccessibilityCallsAndCaptureResumesAfterwards() throws {
    let fixture = LoopFixture()
    fixture.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    fixture.run(for: 60)
    #expect(try fixture.records().isEmpty)
    #expect(fixture.tree.calls.isEmpty)
    fixture.presence = Presence(idleSeconds: 200, locked: false, asleep: false)
    fixture.run(for: 60)
    #expect(try fixture.records().isEmpty)
    fixture.presence = present
    fixture.run(for: 2)
    #expect(try fixture.triggers() == ["heartbeat"])
    #expect(fixture.logged == ["silent: locked", "silent: idle", "capturing again"])
}

@Test func countsTimedOutAndCutOffCaptures() throws {
    let fixture = LoopFixture()
    fixture.windowText = WindowTextSettings(textCapBytes: 3)
    fixture.run(for: 2)
    let stuck = fixture.tree.text("stuck")
    stuck.hangs = ["AXValue"]
    fixture.focus.notes.children.append(stuck)
    fixture.run(for: 30)
    let summary = fixture.counts.take()
    #expect(summary.written == 2)
    #expect(summary.cutOff == 2)
    #expect(summary.timedOut == 1)
    #expect(summary.slowestRead >= fixture.tree.callTimeout)
}

@Test func skipsCapturesWithoutAccessibility() throws {
    let fixture = LoopFixture()
    fixture.trusted = false
    fixture.run(for: 40)
    #expect(try fixture.records().isEmpty)
    #expect(fixture.counts.take().written == 0)
}

@Test func countsWritesTheSpoolRefuses() throws {
    let fixture = LoopFixture()
    let other = fixture.spool.writer()
    try other.start()
    fixture.run(for: 2)
    let summary = fixture.counts.take()
    #expect(summary.written == 0)
    #expect(summary.failed == 1)
    #expect(summary.description.hasSuffix(", 1 failed to write (last: another agent is writing to \(fixture.spool.directory.path))"))
}

@Test func aSwitchWithoutAccessibilityIsCapturedOnceItIsGranted() throws {
    let fixture = LoopFixture()
    fixture.trusted = false
    fixture.run(for: 5)
    fixture.focus.focused = chrome
    fixture.run(for: 5)
    fixture.trusted = true
    fixture.run(for: 0.5)
    #expect(try fixture.triggers() == ["app"])
}

@Test func aDenylistedAppYieldsExcludedRecordsOnSwitchAndHeartbeatWithNoCallsOnItsWindow() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    fixture.focus.focused = onePassword
    fixture.run(for: 3)
    fixture.focus.vault.attributes["AXTitle"] = "Another item"
    fixture.run(for: 60)
    let records = try fixture.records()
    #expect(try fixture.kinds() == ["capture", "excluded", "excluded", "excluded"])
    #expect(try fixture.triggers() == ["heartbeat", "app", "heartbeat", "heartbeat"])
    for excluded in records.dropFirst() {
        #expect(excluded["app_name"] as? String == "1Password")
        #expect(excluded["bundle_id"] as? String == "com.1password.1password")
        #expect(excluded["window_title"] is NSNull)
        #expect(excluded["text"] is NSNull)
    }
    #expect(fixture.focus.passwordAppCalls().isEmpty)
    let summary = fixture.counts.take()
    #expect(summary.written == 1)
    #expect(summary.excluded == 3)
}

@Test func switchingAwayFromADenylistedAppCapturesTheNextApp() throws {
    let fixture = LoopFixture()
    fixture.focus.focused = onePassword
    fixture.run(for: 2)
    fixture.focus.focused = plainApp
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["excluded", "capture"])
    #expect(try fixture.triggers() == ["heartbeat", "app"])
    #expect(fixture.focus.passwordAppCalls().isEmpty)
}

@Test func pausingWritesOnePausedRecordAndNothingElseUntilResumed() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    #expect(try fixture.pause.pause())
    #expect(try !fixture.pause.pause())
    fixture.run(for: 1)
    let callsWhilePaused = fixture.tree.calls.count
    fixture.focus.focused = chrome
    fixture.run(for: 120)
    #expect(fixture.tree.calls.count == callsWhilePaused)
    #expect(try fixture.kinds() == ["capture", "paused"])
    #expect(try fixture.resumeAndRun(for: 2) == ["capture", "paused", "resumed", "capture"])
    #expect(try fixture.records().last?["trigger"] as? String == "app")
    #expect(fixture.logged == ["silent: paused", "capturing again"])
}

@Test func aPauseSurvivesARestartOfTheLoopWithoutAnotherRecord() throws {
    let fixture = LoopFixture()
    fixture.run(for: 0.5)
    try fixture.pause.pause()
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["paused"])
    let callsBeforeRestart = fixture.tree.calls.count
    fixture.restart()
    fixture.run(for: 60)
    #expect(try fixture.kinds() == ["paused"])
    #expect(fixture.tree.calls.count == callsBeforeRestart)
    #expect(try fixture.resumeAndRun(for: 2) == ["paused", "resumed", "capture"])
}

@Test func aLoopStartedWhilePausedWritesNoRecordUntilResumed() throws {
    let fixture = LoopFixture()
    try fixture.pause.pause()
    fixture.restart()
    fixture.run(for: 60)
    #expect(try fixture.records().isEmpty)
    #expect(fixture.logged.isEmpty)
    #expect(try fixture.resumeAndRun(for: 2) == ["resumed", "capture"])
}

@Test func unlockingWhilePausedWritesNoResumedRecord() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    try fixture.pause.pause()
    fixture.run(for: 1)
    fixture.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    fixture.run(for: 30)
    fixture.presence = present
    fixture.run(for: 30)
    #expect(try fixture.kinds() == ["capture", "paused"])
    fixture.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    fixture.run(for: 1)
    #expect(try fixture.resumeAndRun(for: 30) == ["capture", "paused", "resumed"])
    fixture.presence = present
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["capture", "paused", "resumed", "capture"])
    #expect(fixture.logged == [
        "silent: paused", "silent: paused, locked", "silent: paused", "silent: paused, locked", "silent: locked",
        "capturing again",
    ])
}

@Test func aDenylistedAppWhilePausedWritesNothing() throws {
    let fixture = LoopFixture()
    try fixture.pause.pause()
    fixture.restart()
    fixture.focus.focused = onePassword
    fixture.run(for: 60)
    #expect(try fixture.records().isEmpty)
}

extension LoopFixture {
    func resumeAndRun(for seconds: TimeInterval) throws -> [String] {
        #expect(try pause.resume())
        #expect(try !pause.resume())
        run(for: seconds)
        return try kinds()
    }
}

@Test func excludedRecordsNeedNoAccessibilityGrant() throws {
    let fixture = LoopFixture()
    fixture.trusted = false
    fixture.focus.focused = onePassword
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["excluded"])
}
