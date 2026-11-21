import Foundation
import Testing
@testable import CaptureAgent

final class LoopFixture {
    let focus = FocusFixture()
    let spool = TempSpool()
    let counts = CaptureCounts()
    var windowText = WindowTextSettings()
    var denylist = Denylist()
    var screenshots = ScreenshotSettings(recognitionTimeout: 120)
    var images: (any ImageStore)?
    var recognizedText: @Sendable (URL) throws -> String = { _ in "" }
    var logged: [String] = []
    private lazy var writer = spool.writer()
    lazy var screenshotGate = ScreenshotRefusingSpool(writer: writer, refusals: 0)

    var mac: ScriptedMac { focus.mac }
    var settings: AgentSettings {
        var settings = AgentSettings(folder: spool.directory.appendingPathComponent("folder"), spoolDirectory: spool.directory)
        settings.windowText = windowText
        settings.denylist = denylist
        settings.screenshots = screenshots
        return settings
    }
    var pause: PauseSwitch { settings.pause }

    lazy var loop: CaptureLoop<ScriptedMac> = makeLoop()

    func makeLoop() -> CaptureLoop<ScriptedMac> {
        CaptureLoop(
            settings: settings,
            mac: mac,
            spool: screenshotGate,
            images: images ?? JPEGImageStore(folder: settings.folder, longEdge: screenshots.longEdge, quality: screenshots.quality),
            recognize: recognizedText,
            counts: counts,
            log: { self.logged.append($0) }
        )
    }

    func restart() {
        loop = makeLoop()
    }

    func run(for seconds: TimeInterval, waitingForScreenshots: Bool = true) {
        let end = mac.clock + seconds
        loop.run { mac.clock < end }
        if waitingForScreenshots { waitForScreenshots() }
    }

    func waitForScreenshots() {
        loop.waitForScreenshots()
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
        try withoutScreenshots().map { $0["trigger"] as! String }
    }

    func kinds() throws -> [String] {
        try withoutScreenshots().map { $0["kind"] as! String }
    }

    func withoutScreenshots() throws -> [[String: Any]] {
        try records().filter { $0["kind"] as? String != ScreenshotRecord.kind }
    }

    func screenshotRecords() throws -> [[String: Any]] {
        try records().filter { $0["kind"] as? String == ScreenshotRecord.kind }
    }
}

@Test func writesAHeartbeatCaptureOfTheFocusedWindow() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    let records = try fixture.withoutScreenshots()
    #expect(records.count == 1)
    #expect(records[0]["kind"] as? String == "capture")
    #expect(records[0]["trigger"] as? String == "heartbeat")
    #expect(records[0]["app_name"] as? String == "TextEdit")
    #expect(records[0]["bundle_id"] as? String == "com.apple.TextEdit")
    #expect(records[0]["window_title"] as? String == "Notes")
    #expect(records[0]["text"] as? String == "hello")
    #expect(records[0]["captured_at"] as? String == "2026-11-18T09:00:01.002Z")
    #expect(fixture.counts.take().written == 1)
}

@Test func capturesAnAppSwitchAndATabSwitchOncePerSettledChange() throws {
    let fixture = LoopFixture()
    fixture.run(for: 10)
    fixture.mac.focused = chrome
    fixture.run(for: 5)
    fixture.focus.tab.attributes["AXTitle"] = "Pull requests"
    fixture.run(for: 5)
    let records = try fixture.withoutScreenshots()
    #expect(try fixture.triggers() == ["heartbeat", "app", "title"])
    #expect(records[1]["app_name"] as? String == "Google Chrome")
    #expect(records[2]["window_title"] as? String == "Pull requests")
}

@Test func silenceMakesNoAccessibilityCallsAndCaptureResumesAfterwards() throws {
    let fixture = LoopFixture()
    fixture.mac.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    fixture.run(for: 60)
    #expect(try fixture.records().isEmpty)
    #expect(fixture.mac.calls.isEmpty)
    fixture.mac.presence = Presence(idleSeconds: 200, locked: false, asleep: false)
    fixture.run(for: 60)
    #expect(try fixture.records().isEmpty)
    fixture.mac.presence = present
    fixture.run(for: 2)
    #expect(try fixture.triggers() == ["heartbeat"])
    #expect(fixture.logged == ["silent: locked", "silent: idle", "capturing again"])
}

@Test func countsTimedOutAndCutOffCaptures() throws {
    let fixture = LoopFixture()
    fixture.windowText = WindowTextSettings(textCapBytes: 3)
    fixture.run(for: 2)
    let stuck = fixture.mac.text("stuck")
    stuck.hangs = ["AXValue"]
    fixture.focus.notes.children.append(stuck)
    fixture.run(for: 30)
    let summary = fixture.counts.take()
    #expect(summary.written == 2)
    #expect(summary.cutOff == 2)
    #expect(summary.timedOut == 1)
    #expect(summary.slowestRead >= fixture.mac.callTimeout)
}

@Test func skipsCapturesWithoutAccessibility() throws {
    let fixture = LoopFixture()
    fixture.mac.trusted = false
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
    fixture.mac.trusted = false
    fixture.run(for: 5)
    fixture.mac.focused = chrome
    fixture.run(for: 5)
    fixture.mac.trusted = true
    fixture.run(for: 0.5)
    #expect(try fixture.triggers() == ["app"])
}

@Test func aDenylistedAppYieldsExcludedRecordsOnSwitchAndHeartbeatWithNoCallsOnItsWindow() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    fixture.mac.focused = onePassword
    fixture.run(for: 3)
    fixture.focus.vault.attributes["AXTitle"] = "Another item"
    fixture.run(for: 60)
    let records = try fixture.withoutScreenshots()
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
    fixture.mac.focused = onePassword
    fixture.run(for: 2)
    fixture.mac.focused = plainApp
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
    let callsWhilePaused = fixture.mac.calls.count
    fixture.mac.focused = chrome
    fixture.run(for: 120)
    #expect(fixture.mac.calls.count == callsWhilePaused)
    #expect(try fixture.kinds() == ["capture", "paused"])
    #expect(try fixture.resumeAndRun(for: 2) == ["capture", "paused", "resumed", "capture"])
    #expect(try fixture.withoutScreenshots().last?["trigger"] as? String == "app")
    #expect(fixture.logged == ["silent: paused", "capturing again"])
}

@Test func aPauseSurvivesARestartOfTheLoopWithoutAnotherRecord() throws {
    let fixture = LoopFixture()
    fixture.run(for: 0.5)
    try fixture.pause.pause()
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["paused"])
    let callsBeforeRestart = fixture.mac.calls.count
    fixture.restart()
    fixture.run(for: 60)
    #expect(try fixture.kinds() == ["paused"])
    #expect(fixture.mac.calls.count == callsBeforeRestart)
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
    fixture.mac.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    fixture.run(for: 30)
    fixture.mac.presence = present
    fixture.run(for: 30)
    #expect(try fixture.kinds() == ["capture", "paused"])
    fixture.mac.presence = Presence(idleSeconds: 0, locked: true, asleep: false)
    fixture.run(for: 1)
    #expect(try fixture.resumeAndRun(for: 30) == ["capture", "paused", "resumed"])
    fixture.mac.presence = present
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
    fixture.mac.focused = onePassword
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
    fixture.mac.trusted = false
    fixture.mac.focused = onePassword
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["excluded"])
}

@Test func sleepWritesASleptRecordAndWakeAWokeRecordWithNothingBetween() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    let sleptAt = SpoolTime(fixture.mac.now()).iso8601
    fixture.mac.presence.asleep = true
    fixture.run(for: 600)
    #expect(try fixture.kinds() == ["capture", "slept"])
    let wokeAt = SpoolTime(fixture.mac.now()).iso8601
    fixture.mac.presence.asleep = false
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["capture", "slept", "woke", "capture"])
    let records = try fixture.withoutScreenshots()
    #expect(records[1]["captured_at"] as? String == sleptAt)
    #expect(records[2]["captured_at"] as? String == wokeAt)
    for record in records[1...2] {
        for key in ["trigger", "app_name", "bundle_id", "window_title", "text", "full_text_bytes"] {
            #expect(record[key] is NSNull, "\(record["kind"]!) \(key)")
        }
    }
    #expect(fixture.logged == ["silent: asleep", "capturing again"])
}

@Test func sleepWhilePausedWritesNoSleptOrWokeRecord() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    try fixture.pause.pause()
    fixture.run(for: 1)
    fixture.mac.presence.asleep = true
    fixture.run(for: 60)
    fixture.mac.presence.asleep = false
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["capture", "paused"])
    #expect(try fixture.resumeAndRun(for: 2) == ["capture", "paused", "resumed", "capture"])
}

@Test func aWakeWithoutARecordedSleepWritesNoWokeRecord() throws {
    let fixture = LoopFixture()
    try fixture.pause.pause()
    fixture.restart()
    fixture.mac.presence.asleep = true
    fixture.run(for: 1)
    try fixture.pause.resume()
    fixture.mac.presence.asleep = false
    fixture.run(for: 2)
    #expect(try fixture.kinds() == ["resumed", "capture"])
}

@Test func aSleepAfterALostWakeIsStillRecorded() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    fixture.mac.sleepChanged(.willSleep)
    fixture.mac.sleepChanged(.willSleep)
    fixture.mac.sleepChanged(.didWake)
    fixture.mac.sleepChanged(.didWake)
    #expect(try fixture.kinds() == ["capture", "slept", "slept", "woke"])
}

@Test func aCaptureDueAsTheMacFallsAsleepIsNotWrittenAfterTheSleptRecord() throws {
    let fixture = LoopFixture()
    var slept = false
    fixture.mac.onCall = { _ in
        guard fixture.mac.clock >= 1, !slept else { return }
        slept = true
        fixture.mac.presence.asleep = true
    }
    fixture.run(for: 60)
    #expect(slept)
    #expect(try fixture.kinds() == ["slept"])
}

@Test func anExclusionDueAsTheMacFallsAsleepIsNotWrittenAfterTheSleptRecord() throws {
    let fixture = LoopFixture()
    fixture.mac.focused = onePassword
    var slept = false
    fixture.mac.onCall = { _ in
        guard fixture.mac.clock >= 1, !slept else { return }
        slept = true
        fixture.mac.presence.asleep = true
    }
    fixture.run(for: 60)
    #expect(slept)
    #expect(try fixture.kinds() == ["slept"])
}

@Test func aCaptureWhoseReadSpansTheSleepIsNotWrittenAfterTheSleptRecord() throws {
    let fixture = LoopFixture()
    fixture.mac.onCall = { call in
        if call == "hello.AXValue", !fixture.mac.presence.asleep { fixture.mac.presence.asleep = true }
    }
    fixture.run(for: 60)
    #expect(try fixture.kinds() == ["slept"])
    #expect(try fixture.screenshotRecords().isEmpty)
}

@Test func theMacStillReportsAsleepWhileItsWakeIsHandled() {
    let mac = ScriptedMac()
    let seen = Seen()
    mac.onSleepChange { change, _ in seen.add("\(change) \(mac.samplePresence().asleep)") }
    mac.presence.asleep = true
    mac.presence.asleep = false
    #expect(seen.values == ["willSleep true", "didWake true"])
    #expect(!mac.samplePresence().asleep)
}

@Test func aLoopThatStoppedRecordingSleepWritesNoSleepRecord() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    fixture.loop.stopRecordingSleep()
    fixture.mac.presence.asleep = true
    fixture.mac.presence.asleep = false
    #expect(try fixture.kinds() == ["capture"])
}

private final class Seen: @unchecked Sendable {
    private(set) var values: [String] = []
    func add(_ value: String) { values.append(value) }
}
