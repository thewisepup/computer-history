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
    return greyImage(pixels, width: 9)
}

@Test func theTestImagesHashToTheirBits() {
    for bits: UInt64 in [0, 1, 0b111, 0x8000_0000_0000_0001, 0xffff_0000_ffff_0000] {
        #expect(differenceHash(imageHashing(to: bits)) == FrameHash(bits: bits))
    }
}

@Test func aDuplicateRecordsItsOwnFramesHashAndTheKeptImageAndText() throws {
    let fixture = LoopFixture()
    var pixels = [UInt8](repeating: 128, count: 72)
    fixture.mac.windowImage = { _, _ in .image(greyImage(pixels, width: 9), windowID: 1) }
    fixture.run(for: 2)
    pixels[0] = 129
    fixture.run(for: 30)
    #expect(try fixture.statuses() == ["kept", "duplicate"])
    let shots = try fixture.screenshotRecords()
    #expect(shots.map { $0["perceptual_hash"] as? String } == [0, 1 << 63].map { FrameHash(bits: $0).hex })
    #expect(shots[1]["image_path"] as? String == shots[0]["image_path"] as? String)
    #expect(shots[1]["text_sha256"] as? String == shots[0]["text_sha256"] as? String)
}

@Test(arguments: [
    ("a caret blink", false), ("JPEG re-encoding at the agent's quality", false),
    ("one typed line", true), ("a one-line scroll", true), ("the next page", true),
])
func aTypedLineOrAScrollIsAChangeButACaretOrEncodingNoiseIsNot(change: String, isChange: Bool) throws {
    let fixture = LoopFixture()
    var image = CodePage().image()
    fixture.mac.windowImage = { _, _ in .image(image, windowID: 1) }
    fixture.run(for: 2)
    var page = CodePage()
    switch change {
    case "a caret blink": page.caretAfterLine = 10
    case "one typed line": page.lines[10] += " capture window"
    case "a one-line scroll": page = CodePage(from: 1)
    case "the next page": page = CodePage(from: CodePage.lineCount)
    default: break
    }
    image = change.hasPrefix("JPEG") ? reencoded(page.image(), quality: Double(fixture.screenshots.quality) / 100) : page.image()
    fixture.run(for: 30)
    #expect(try fixture.statuses() == ["kept", isChange ? "kept" : "duplicate"])
}

func spoolDate(_ text: String?) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return text.flatMap(formatter.date(from:))
}

@Test func anUnchangedWindowGetsANewKeptImageOnceItsLastIsOlderThanTheLimit() throws {
    let fixture = LoopFixture()
    fixture.screenshots.keepAfter = 120
    fixture.run(for: 400)
    let shots = try fixture.screenshotRecords()
    var lastKept: (time: Date, path: String)?
    for shot in shots {
        let time = try #require(spoolDate(shot["captured_at"] as? String))
        let expected = lastKept.map { time.timeIntervalSince($0.time) > 120 } ?? true
        #expect(shot["status"] as? String == (expected ? "kept" : "duplicate"))
        if expected { lastKept = (time, shot["image_path"] as! String) } else { #expect(shot["image_path"] as? String == lastKept?.path) }
    }
    #expect(shots.filter { $0["status"] as? String == "kept" }.count >= 3)
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

let start = Date(timeIntervalSince1970: 1_000_000)

func thumbnail(_ pixels: [UInt8], width: Int = 160) -> FrameThumbnail {
    FrameThumbnail(width: width, height: pixels.count / width, pixels: pixels)
}

func keptFrame(_ thumbnail: FrameThumbnail, at time: Date = start) -> FrameDedup.KeptFrame {
    FrameDedup.KeptFrame(imagePath: "screenshots/a.jpg", thumbnail: thumbnail, keptAt: time, text: KeptText())
}

@Test(arguments: [(0, true), (7, true), (8, false), (16_000, false)])
func aFrameIsADuplicateOnlyWhenFewerPixelsChangedThanTheThreshold(changed: Int, duplicate: Bool) throws {
    var dedup = FrameDedup(changePercent: 0.05, keepAfter: 600)
    let window = FrameDedup.Window(id: 1, title: "Notes")
    let white = [UInt8](repeating: 255, count: 16_000)
    dedup.remember(keptFrame(thumbnail(white)), for: window)
    let frame = (0..<16_000).map { $0 < changed ? UInt8(255 - FrameDedup.pixelTolerance - 1) : 255 }
    let match = dedup.see(thumbnail(frame), in: window, at: start)
    #expect((match != nil) == duplicate)
}

@Test func aPixelWithinTheToleranceHasNotChanged() throws {
    var dedup = FrameDedup(changePercent: 0.05, keepAfter: 600)
    let window = FrameDedup.Window(id: 1, title: "Notes")
    dedup.remember(keptFrame(thumbnail([UInt8](repeating: 128, count: 16_000))), for: window)
    let match = dedup.see(thumbnail([UInt8](repeating: UInt8(128 + FrameDedup.pixelTolerance), count: 16_000)), in: window, at: start)
    #expect(match != nil)
}

@Test(arguments: [(0.0, true), (600.0, true), (600.5, false)])
func aMatchOlderThanTheLimitIsNoDuplicate(age: TimeInterval, duplicate: Bool) throws {
    var dedup = FrameDedup(changePercent: 0.05, keepAfter: 600)
    let window = FrameDedup.Window(id: 1, title: "Notes")
    let frame = thumbnail([UInt8](repeating: 0, count: 16_000))
    dedup.remember(keptFrame(frame), for: window)
    let match = dedup.see(frame, in: window, at: start.addingTimeInterval(age))
    #expect((match != nil) == duplicate)
}

@Test func aThresholdOfZeroCountsEveryFrameAsChanged() throws {
    var dedup = FrameDedup(changePercent: 0, keepAfter: 600)
    let window = FrameDedup.Window(id: 1, title: "Notes")
    let frame = thumbnail([UInt8](repeating: 0, count: 16_000))
    dedup.remember(keptFrame(frame), for: window)
    let match = dedup.see(frame, in: window, at: start)
    #expect(match == nil)
}

@Test func aFrameOfAnotherSizeIsAChange() throws {
    var dedup = FrameDedup(changePercent: 0.05, keepAfter: 600)
    let window = FrameDedup.Window(id: 1, title: "Notes")
    dedup.remember(keptFrame(thumbnail([UInt8](repeating: 0, count: 16_000))), for: window)
    let match = dedup.see(thumbnail([UInt8](repeating: 0, count: 16_000), width: 100), in: window, at: start)
    #expect(match == nil)
}

@Test func aWindowIsItsWindowIDAndItsTitle() throws {
    var dedup = FrameDedup(changePercent: 0.05, keepAfter: 600)
    let frame = thumbnail([UInt8](repeating: 0, count: 16_000))
    dedup.remember(keptFrame(frame), for: FrameDedup.Window(id: 1, title: "Notes"))
    let otherWindow = dedup.see(frame, in: FrameDedup.Window(id: 2, title: "Notes"), at: start)
    let otherTitle = dedup.see(frame, in: FrameDedup.Window(id: 1, title: "Inbox"), at: start)
    let same = dedup.see(frame, in: FrameDedup.Window(id: 1, title: "Notes"), at: start)
    #expect(otherWindow == nil)
    #expect(otherTitle == nil)
    #expect(same != nil)
}

@Test(arguments: [(1600, 1000, 160, 100), (900, 1440, 100, 160), (1440, 60, 160, 7), (120, 80, 120, 80), (9, 8, 9, 8)])
func aThumbnailKeepsTheAspectRatioAtALongEdgeOf160AndIsNeverEnlarged(width: Int, height: Int, thumbWidth: Int, thumbHeight: Int) throws {
    let thumb = try #require(FrameThumbnail(fixtureImage(width: width, height: height)))
    #expect(thumb.width == thumbWidth)
    #expect(thumb.height == thumbHeight)
    #expect(thumb.pixels.count == thumbWidth * thumbHeight)
}

@Test func aThumbnailPixelIsTheAverageBrightnessOfTheBlockItCovers() throws {
    var pixels = [UInt8](repeating: 0, count: 320 * 2)
    for column in stride(from: 0, to: 320, by: 2) { pixels[column] = 200 }
    let thumb = try #require(FrameThumbnail(greyImage(pixels, width: 320)))
    #expect(thumb.width == 160)
    #expect(thumb.height == 1)
    #expect(Set(thumb.pixels) == [50])
}
