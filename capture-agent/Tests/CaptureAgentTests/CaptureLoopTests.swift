import Foundation
import Testing
@testable import CaptureAgent

final class LoopFixture {
    let focus = FocusFixture()
    let spool = TempSpool()
    let counts = CaptureCounts()
    var presence = present
    var trusted = true
    var windowText = WindowTextSettings()
    var logged: [String] = []
    private var nextTick: TimeInterval = 0

    var tree: FakeAccessibilityTree { focus.tree }

    lazy var loop: CaptureLoop<FakeElement> = {
        let reader = tree.reader(focus.apps, settings: windowText)
        return CaptureLoop(
            settings: CaptureSettings(),
            focus: focus.watch(),
            presence: { self.presence },
            accessibilityTrusted: { self.trusted },
            read: reader.read,
            spool: spool.writer(),
            counts: counts,
            uptime: { self.tree.now },
            now: { self.spool.clock.now },
            log: { self.logged.append($0) }
        )
    }()

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
