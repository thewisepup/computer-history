import CoreGraphics
import Foundation
import Testing
@testable import CaptureAgent

func savedImages(in folder: URL) -> [String] {
    let root = folder.appendingPathComponent(JPEGImageStore.folderName)
    let files = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)?.allObjects as? [URL] ?? []
    return files.filter { $0.pathExtension == "jpg" }.map(\.lastPathComponent)
}

@Test func everyCaptureIsFollowedByOneKeptScreenshotRecordWhoseImageIsSaved() throws {
    let fixture = LoopFixture()
    fixture.mac.windowImage = { _, _ in .image(fixtureImage(width: 2880, height: 1800)) }
    fixture.run(for: 2)
    let records = try fixture.records()
    try #require(records.map { $0["kind"] as? String } == ["capture", "screenshot"])
    let (capture, screenshot) = (records[0], records[1])
    #expect(screenshot["status"] as? String == "kept")
    #expect(screenshot["capture_id"] as? String == capture["id"] as? String)
    #expect(screenshot["captured_at"] as? String == capture["captured_at"] as? String)
    #expect(screenshot["window_title"] as? String == "Notes")
    #expect(screenshot["text"] as? String == "")
    #expect(screenshot["full_text_bytes"] as? Int == 0)
    #expect((screenshot["perceptual_hash"] as? String)?.wholeMatch(of: /[0-9a-f]{16}/) != nil)
    let id = try #require(screenshot["id"] as? String)
    let path = try #require(screenshot["image_path"] as? String)
    #expect(path.wholeMatch(of: try Regex("screenshots/\\d{4}-\\d{2}-\\d{2}/\(id)\\.jpg")) != nil)
    let file = fixture.settings.folder.appendingPathComponent(path)
    #expect(screenshot["image_bytes"] as? Int == (try FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int))
    #expect(pixelSize(ofJPEG: file).map { [$0.width, $0.height] } == [1440, 900])
    #expect(fixture.mac.windowImageRequests == [plainApp.processIdentifier])
}

@Test func theCaptureRecordIsInTheSpoolBeforeTheScreenshotIsTaken() throws {
    let fixture = LoopFixture()
    var kindsWhenTaken: [[String]] = []
    fixture.mac.windowImage = { _, _ in
        kindsWhenTaken.append((try? fixture.records().map { $0["kind"] as! String }) ?? [])
        return .failed
    }
    fixture.run(for: 2)
    #expect(kindsWhenTaken == [["capture"]])
}

@Test(arguments: [(WindowImage.noPermission, "no-permission"), (.failed, "failed")])
func aMissingGrantOrAFailedPictureIsRecordedAndTheCaptureKeepsItsText(image: WindowImage, status: String) throws {
    let fixture = LoopFixture()
    fixture.mac.windowImage = { _, _ in image }
    fixture.run(for: 2)
    let records = try fixture.records()
    #expect(records.map { $0["kind"] as? String } == ["capture", "screenshot"])
    #expect(records[0]["text"] as? String == "hello")
    #expect(records[1]["status"] as? String == status)
    #expect(records[1]["image_path"] is NSNull)
    #expect(savedImages(in: fixture.settings.folder).isEmpty)
}

struct RefusingImageStore: ImageStore {
    func save(_ image: CGImage, id: UUID, at date: Date) throws -> SavedImage {
        throw ImageStoreError(description: "disk full")
    }

    func remove(_ path: String) {}
}

final class ScreenshotRefusingSpool: SpoolAppender, @unchecked Sendable {
    let writer: SpoolWriter
    var refusals: Int

    init(writer: SpoolWriter, refusals: Int) {
        self.writer = writer
        self.refusals = refusals
    }

    func append(_ record: some SpoolLine) throws {
        if record is ScreenshotRecord, refusals > 0 {
            refusals -= 1
            throw ImageStoreError(description: "spool refused")
        }
        try writer.append(record)
    }
}

@Test func anImageThatCannotBeSavedIsRecordedAsFailed() throws {
    let fixture = LoopFixture()
    fixture.images = RefusingImageStore()
    fixture.run(for: 2)
    let records = try fixture.records()
    #expect(records.map { $0["kind"] as? String } == ["capture", "screenshot"])
    #expect(records[1]["status"] as? String == "failed")
}

@Test func aFocusedPasswordFieldTakesNoPicture() throws {
    let fixture = LoopFixture()
    let password = fixture.mac.node("password", role: "AXTextField", ["AXSubrole": "AXSecureTextField"])
    fixture.mac.apps[plainApp.processIdentifier]!.focusedElement = password
    fixture.run(for: 2)
    #expect(try fixture.screenshotRecords().map { $0["status"] as? String } == ["secure-field"])
    #expect(fixture.mac.windowImageRequests.isEmpty)
    let field = fixture.mac.node("field", role: "AXTextField")
    fixture.mac.apps[plainApp.processIdentifier]!.focusedElement = field
    fixture.run(for: 30)
    #expect(try fixture.screenshotRecords().map { $0["status"] as? String } == ["secure-field", "kept"])
}

@Test func withScreenshotsOffNoPictureIsTakenAndNoScreenshotRecordWritten() throws {
    let fixture = LoopFixture()
    fixture.screenshots.enabled = false
    fixture.run(for: 40)
    #expect(try fixture.kinds() == ["capture", "capture"])
    #expect(try fixture.screenshotRecords().isEmpty)
    #expect(fixture.mac.windowImageRequests.isEmpty)
    #expect(savedImages(in: fixture.settings.folder).isEmpty)
}

@Test func onlyCapturesGetAScreenshotRecordAndEachGetsExactlyOneRightAfterIt() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    fixture.mac.focused = onePassword
    fixture.run(for: 40)
    fixture.mac.focused = chrome
    fixture.run(for: 3)
    try fixture.pause.pause()
    fixture.run(for: 40)
    try fixture.pause.resume()
    fixture.run(for: 3)
    let records = try fixture.records()
    #expect(records.map { $0["kind"] as! String } == [
        "capture", "screenshot", "excluded", "excluded", "capture", "screenshot", "paused", "resumed", "capture", "screenshot",
    ])
    for (index, record) in records.enumerated() where record["kind"] as? String == "screenshot" {
        #expect(record["capture_id"] as? String == records[index - 1]["id"] as? String)
    }
    #expect(Set(savedImages(in: fixture.settings.folder)) == Set(try fixture.screenshotRecords().map { "\($0["id"] as! String).jpg" }))
    #expect(fixture.mac.windowImageRequests == [plainApp.processIdentifier, chrome.processIdentifier, chrome.processIdentifier])
}

@Test func theHashIsTheSameForTheSamePictureAndDiffersForAnother() {
    let first = differenceHash(fixtureImage(width: 640, height: 400, seed: 1))
    #expect(first == differenceHash(fixtureImage(width: 1280, height: 800, seed: 1)))
    #expect(first != differenceHash(fixtureImage(width: 640, height: 400, seed: 2)))
}

@Test(arguments: ["focused element times out", "role times out", "subrole times out", "no role"])
func aPasswordFieldCheckWithNoAnswerTakesNoPicture(unanswered: String) throws {
    let fixture = LoopFixture()
    let app = fixture.mac.apps[plainApp.processIdentifier]!
    let field = fixture.mac.node("field", role: "AXTextField")
    app.focusedElement = field
    switch unanswered {
    case "focused element times out": app.hangs = ["AXFocusedUIElement"]
    case "role times out": field.hangs = ["AXRole"]
    case "subrole times out": field.hangs = ["AXSubrole"]
    default: field.attributes["AXRole"] = nil
    }
    fixture.run(for: 2)
    #expect(try fixture.screenshotRecords().map { $0["status"] as? String } == ["failed"])
    #expect(fixture.mac.windowImageRequests.isEmpty)
}

@Test func anAppWithNoFocusedElementIsStillPhotographed() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    #expect(try fixture.screenshotRecords().map { $0["status"] as? String } == ["kept"])
}

@Test func thePictureIsAskedForByTheFocusedWindowsFrameAndTheLongEdge() throws {
    let fixture = LoopFixture()
    fixture.screenshots.longEdge = 1024
    fixture.focus.notes.bounds = CGRect(x: 10, y: 20, width: 800, height: 600)
    var asked: [FocusedWindow] = []
    var longEdges: [Int] = []
    fixture.mac.windowImage = { window, longEdge in
        asked.append(window)
        longEdges.append(longEdge)
        return .failed
    }
    fixture.run(for: 2)
    #expect(asked == [FocusedWindow(processIdentifier: plainApp.processIdentifier, title: "Notes", frame: CGRect(x: 10, y: 20, width: 800, height: 600))])
    #expect(longEdges == [1024])
}

@Test(arguments: [true, false])
func aWindowWhoseFrameCannotBeReadIsNotPhotographed(timesOut: Bool) throws {
    let fixture = LoopFixture()
    if timesOut { fixture.focus.notes.hangs = ["AXFrame"] } else { fixture.focus.notes.bounds = nil }
    fixture.run(for: 2)
    #expect(try fixture.screenshotRecords().map { $0["status"] as? String } == ["failed"])
    #expect(fixture.mac.windowImageRequests.isEmpty)
}

@Test(arguments: ["pause", "lock", "sleep", "idle", "another app", "another title"])
func aChangeDuringTheTextReadTakesNoPictureAndRecordsAFailedScreenshot(change: String) throws {
    let fixture = LoopFixture()
    var changed = false
    fixture.mac.onCall = { call in
        guard call == "hello.AXValue", !changed else { return }
        changed = true
        switch change {
        case "pause": _ = try? fixture.pause.pause()
        case "lock": fixture.mac.presence.locked = true
        case "sleep": fixture.mac.presence.asleep = true
        case "idle": fixture.mac.presence.idleSeconds = 600
        case "another app": fixture.mac.focused = chrome
        default: fixture.focus.notes.attributes["AXTitle"] = "Renamed"
        }
    }
    fixture.run(for: 1.5)
    let records = try fixture.records()
    #expect(records.map { $0["kind"] as? String } == ["capture", "screenshot"])
    #expect(records.first?["text"] as? String == "hello")
    #expect(records.last?["status"] as? String == "failed")
    #expect(fixture.mac.windowImageRequests.isEmpty)
}

@Test func aKeptImageWhoseRecordCannotBeWrittenIsRemovedAndCountedApart() throws {
    let fixture = LoopFixture()
    fixture.screenshotsTheSpoolRefuses = .max
    fixture.run(for: 2)
    #expect(try fixture.records().map { $0["kind"] as? String } == ["capture"])
    #expect(savedImages(in: fixture.settings.folder).isEmpty)
    let summary = fixture.counts.take()
    #expect(summary.written == 1)
    #expect(summary.failed == 0)
    #expect(summary.screenshotsFailed == 1)
    #expect(summary.description.hasSuffix(", 1 screenshot records failed to write (last: spool refused)"))
}
