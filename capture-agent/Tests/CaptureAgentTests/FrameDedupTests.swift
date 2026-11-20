import Foundation
import Testing
@testable import CaptureAgent

extension LoopFixture {
    func statuses() throws -> [String] {
        try screenshotRecords().map { $0["status"] as! String }
    }

    func showTitle(_ title: String) {
        focus.notes.attributes["AXTitle"] = title
        run(for: 3)
    }
}

@Test func anUnchangedWindowIsKeptOnceThenRecordedAsDuplicatesOfThatImage() throws {
    let fixture = LoopFixture()
    fixture.run(for: 100)
    let shots = try fixture.screenshotRecords()
    try #require(shots.count >= 3)
    #expect(try fixture.statuses() == ["kept"] + Array(repeating: "duplicate", count: shots.count - 1))
    let captures = try fixture.withoutScreenshots()
    #expect(shots.map { $0["capture_id"] as! String } == captures.map { $0["id"] as! String })
    let kept = shots[0]
    for duplicate in shots.dropFirst() {
        #expect(duplicate["id"] as? String != kept["id"] as? String)
        for key in ["image_path", "perceptual_hash", "text", "text_sha256", "full_text_bytes", "text_cut_off", "window_title"] {
            #expect(duplicate[key] as? NSObject == kept[key] as? NSObject, "\(key)")
        }
        #expect(duplicate["image_bytes"] is NSNull)
    }
    #expect(savedImages(in: fixture.settings.folder) == ["\(kept["id"] as! String).jpg"])
}

@Test func flippingBetweenTwoWindowsKeepsOneImagePerWindow() throws {
    let fixture = LoopFixture()
    fixture.mac.windowImage = { window, _ in .image(fixtureImage(width: 1600, height: 1000, seed: Int(window.processIdentifier))) }
    for _ in 0..<3 {
        fixture.mac.focused = plainApp
        fixture.run(for: 3)
        fixture.mac.focused = chrome
        fixture.run(for: 3)
    }
    #expect(try fixture.statuses() == ["kept", "kept", "duplicate", "duplicate", "duplicate", "duplicate"])
    let shots = try fixture.screenshotRecords()
    #expect(savedImages(in: fixture.settings.folder).count == 2)
    for (index, shot) in shots.enumerated().dropFirst(2) {
        #expect(shot["image_path"] as? String == shots[index % 2]["image_path"] as? String)
        #expect(shot["app_name"] as? String == shots[index % 2]["app_name"] as? String)
    }
}

@Test func aChangedFrameIsKeptAndLaterFramesAreComparedWithIt() throws {
    let fixture = LoopFixture()
    var seed = 1
    fixture.mac.windowImage = { _, _ in .image(fixtureImage(width: 1600, height: 1000, seed: seed)) }
    fixture.run(for: 40)
    seed = 2
    fixture.run(for: 60)
    #expect(try fixture.statuses() == ["kept", "duplicate", "kept", "duplicate"])
    let shots = try fixture.screenshotRecords()
    #expect(shots[3]["image_path"] as? String == shots[2]["image_path"] as? String)
    #expect(shots[2]["image_path"] as? String != shots[0]["image_path"] as? String)
    #expect(savedImages(in: fixture.settings.folder).count == 2)
}

@Test func onlyTheMostRecentlySeenWindowsAreRemembered() throws {
    let fixture = LoopFixture()
    let titles = (1...FrameDedup.windows + 1).map { "Note \($0)" }
    titles.forEach(fixture.showTitle)
    fixture.showTitle(titles[1])
    fixture.showTitle(titles[0])
    #expect(try fixture.statuses() == Array(repeating: "kept", count: titles.count) + ["duplicate", "kept"])
}

@Test func aRenamedWindowGetsANewKeptImageAndItsOldTitleIsStillRemembered() throws {
    let fixture = LoopFixture()
    fixture.run(for: 2)
    fixture.showTitle("Notes — Edited")
    fixture.showTitle("Notes")
    #expect(try fixture.statuses() == ["kept", "kept", "duplicate"])
}

@Test func theMemoryStartsEmptyWhenTheAgentRestarts() throws {
    let fixture = LoopFixture()
    fixture.run(for: 40)
    fixture.restart()
    fixture.run(for: 3)
    #expect(try fixture.statuses() == ["kept", "duplicate", "kept"])
}

@Test func aKeptImageTheSpoolRefusedIsForgottenSoTheNextFrameIsKeptAgain() throws {
    let fixture = LoopFixture()
    fixture.screenshotsTheSpoolRefuses = 1
    fixture.run(for: 70)
    #expect(try fixture.statuses() == ["kept", "duplicate"])
    let kept = try fixture.screenshotRecords()[0]
    #expect(savedImages(in: fixture.settings.folder) == ["\(kept["id"] as! String).jpg"])
}

@Test(arguments: [(2, 2, true), (2, 3, false), (0, 0, true), (0, 1, false), (32, 32, true)])
func aFrameIsADuplicateWhenAtMostTheThresholdOfItsBitsDiffer(threshold: Int, differing: Int, duplicate: Bool) throws {
    var dedup = FrameDedup(threshold: threshold)
    let capture = captureRecord(text: "", fullTextBytes: 0)
    dedup.remember(.kept(of: capture, imagePath: "screenshots/a.jpg", imageBytes: 10, perceptualHash: FrameHash(bits: 0).hex, text: "", fullTextBytes: 0))
    let frame = FrameHash(bits: (1 << UInt64(differing)) - 1)
    let match = dedup.keptMatch(of: frame, for: captureRecord(text: "", fullTextBytes: 0))
    #expect((match != nil) == duplicate)
}

@Test func aDuplicateCarriesTheKeptRecordsImagePathHashAndRecognizedText() throws {
    let first = captureRecord(text: "", fullTextBytes: 0)
    let kept = ScreenshotRecord.kept(
        of: first, imagePath: "screenshots/2026-11-18/a.jpg", imageBytes: 183_442, perceptualHash: "c3a1f0e2d4b69785",
        text: "Pull requests\nOpen 3", fullTextBytes: 61_204
    )
    var dedup = FrameDedup(threshold: 0)
    dedup.remember(kept)
    let later = captureRecord(text: "", fullTextBytes: 0)
    let found = dedup.keptMatch(of: FrameHash(hex: "c3a1f0e2d4b69785")!, for: later)
    let match = try #require(found)
    let duplicate = ScreenshotRecord.duplicate(of: later, matching: match)
    #expect(duplicate.status == .duplicate)
    #expect(duplicate.captureID == later.id)
    #expect(duplicate.id != kept.id)
    #expect(duplicate.imagePath == kept.imagePath)
    #expect(duplicate.imageBytes == nil)
    #expect(duplicate.perceptualHash == kept.perceptualHash)
    #expect(duplicate.text == kept.text)
    #expect(duplicate.fullTextBytes == kept.fullTextBytes)
    #expect(duplicate.textSHA256 == kept.textSHA256)
    #expect(duplicate.textCutOff == true)
}

@Test func anotherAppWithTheSameTitleIsAnotherWindow() throws {
    var dedup = FrameDedup(threshold: 0)
    let notes = captureRecord(text: "", fullTextBytes: 0)
    dedup.remember(.kept(of: notes, imagePath: "screenshots/a.jpg", imageBytes: 10, perceptualHash: FrameHash(bits: 7).hex, text: "", fullTextBytes: 0))
    let other = SpoolRecord.capture(
        at: notes.capturedAt, trigger: .app, appName: "TextEdit", bundleID: "com.apple.TextEdit", windowTitle: notes.windowTitle,
        text: "", fullTextBytes: 0, timedOut: false
    )
    let otherMatch = dedup.keptMatch(of: FrameHash(bits: 7), for: other)
    let notesMatch = dedup.keptMatch(of: FrameHash(bits: 7), for: notes)
    #expect(otherMatch == nil)
    #expect(notesMatch != nil)
}
