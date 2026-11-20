import CoreGraphics
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

/// A 9x8 grey image whose difference hash is exactly the given bits.
func imageHashing(to bits: UInt64) -> CGImage {
    var pixels: [UInt8] = []
    for row in 0..<8 {
        var shade: UInt8 = 128
        pixels.append(shade)
        for column in 0..<8 {
            shade = bits >> UInt64(63 - (row * 8 + column)) & 1 == 1 ? shade - 10 : shade + 10
            pixels.append(shade)
        }
    }
    let provider = CGDataProvider(data: Data(pixels) as CFData)!
    return CGImage(
        width: 9, height: 8, bitsPerComponent: 8, bitsPerPixel: 8, bytesPerRow: 9, space: CGColorSpaceCreateDeviceGray(),
        bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue), provider: provider, decode: nil,
        shouldInterpolate: false, intent: .defaultIntent
    )!
}

@Test func theTestImagesHashToTheirBits() {
    for bits: UInt64 in [0, 1, 0b111, 0x8000_0000_0000_0001, 0xffff_0000_ffff_0000] {
        #expect(differenceHash(imageHashing(to: bits)) == FrameHash(bits: bits))
    }
}

@Test func aDuplicateRecordsItsOwnFramesHashAndTheKeptImageAndText() throws {
    let fixture = LoopFixture()
    var bits: UInt64 = 0
    fixture.mac.windowImage = { _, _ in .image(imageHashing(to: bits), windowID: 1) }
    fixture.run(for: 2)
    bits = 0b11
    fixture.run(for: 30)
    bits = 0b111
    fixture.run(for: 30)
    #expect(try fixture.statuses() == ["kept", "duplicate", "kept"])
    let shots = try fixture.screenshotRecords()
    #expect(shots.map { $0["perceptual_hash"] as? String } == [0, 0b11, 0b111].map { FrameHash(bits: $0).hex })
    #expect(shots[1]["image_path"] as? String == shots[0]["image_path"] as? String)
    #expect(shots[1]["text_sha256"] as? String == shots[0]["text_sha256"] as? String)
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
    fixture.mac.windowImage = { window, _ in
        .image(fixtureImage(width: 1600, height: 1000, seed: Int(window.processIdentifier)), windowID: CGWindowID(window.processIdentifier))
    }
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

@Test func twoWindowsOfOneAppWithTheSameTitleEachKeepTheirOwnImage() throws {
    let fixture = LoopFixture()
    let app = fixture.mac.apps[plainApp.processIdentifier]!
    let other = fixture.mac.window("Notes", children: [fixture.mac.text("other")])
    for window in [fixture.focus.notes, other, fixture.focus.notes, other] {
        app.focusedWindow = window
        fixture.run(for: 3)
    }
    #expect(try fixture.statuses() == ["kept", "kept", "duplicate", "duplicate"])
    let shots = try fixture.screenshotRecords()
    #expect(shots[0]["image_path"] as? String != shots[1]["image_path"] as? String)
    #expect(shots[2]["image_path"] as? String == shots[0]["image_path"] as? String)
    #expect(shots[3]["image_path"] as? String == shots[1]["image_path"] as? String)
}

@Test func aChangedFrameIsKeptAndLaterFramesAreComparedWithIt() throws {
    let fixture = LoopFixture()
    var seed = 1
    fixture.mac.windowImage = { _, _ in .image(fixtureImage(width: 1600, height: 1000, seed: seed), windowID: 1) }
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
    fixture.screenshotGate.refusals = 1
    fixture.run(for: 70)
    #expect(try fixture.statuses() == ["kept", "duplicate"])
    let kept = try fixture.screenshotRecords()[0]
    #expect(savedImages(in: fixture.settings.folder) == ["\(kept["id"] as! String).jpg"])
}

func keptFrame(hash: FrameHash, text: String = "", fullTextBytes: Int = 0) -> FrameDedup.KeptFrame {
    FrameDedup.KeptFrame(recordID: UUID(), imagePath: "screenshots/a.jpg", hash: hash, text: text, fullTextBytes: fullTextBytes)
}

@Test func aRefusedKeptFrameGivesTheWindowBackItsEarlierKeptFrame() throws {
    let fixture = LoopFixture()
    var bits: UInt64 = 0
    fixture.mac.windowImage = { _, _ in .image(imageHashing(to: bits), windowID: 1) }
    fixture.run(for: 2)
    bits = 0b111
    fixture.screenshotGate.refusals = 1
    fixture.run(for: 30)
    bits = 0
    fixture.run(for: 30)
    #expect(try fixture.statuses() == ["kept", "duplicate"])
    let shots = try fixture.screenshotRecords()
    #expect(shots[1]["image_path"] as? String == shots[0]["image_path"] as? String)
    #expect(savedImages(in: fixture.settings.folder) == ["\(shots[0]["id"] as! String).jpg"])
}

@Test(arguments: [(2, 2, true), (2, 3, false), (0, 0, true), (0, 1, false), (10, 10, true), (10, 11, false)])
func aFrameIsADuplicateWhenAtMostTheThresholdOfItsBitsDiffer(threshold: Int, differing: Int, duplicate: Bool) throws {
    var dedup = FrameDedup(threshold: threshold)
    let window = FrameDedup.Window(id: 1, title: "Notes")
    dedup.remember(keptFrame(hash: FrameHash(bits: 0)), for: window)
    let match = dedup.see(FrameHash(bits: (1 << UInt64(differing)) - 1), in: window)
    #expect((match != nil) == duplicate)
}

@Test func aWindowIsItsWindowIDAndItsTitle() throws {
    var dedup = FrameDedup(threshold: 0)
    dedup.remember(keptFrame(hash: FrameHash(bits: 7)), for: FrameDedup.Window(id: 1, title: "Notes"))
    let otherWindow = dedup.see(FrameHash(bits: 7), in: FrameDedup.Window(id: 2, title: "Notes"))
    let otherTitle = dedup.see(FrameHash(bits: 7), in: FrameDedup.Window(id: 1, title: "Inbox"))
    let same = dedup.see(FrameHash(bits: 7), in: FrameDedup.Window(id: 1, title: "Notes"))
    #expect(otherWindow == nil)
    #expect(otherTitle == nil)
    #expect(same != nil)
}
