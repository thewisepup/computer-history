import Foundation
import Testing
@testable import CaptureAgent

func isScreenshotLine(_ line: String) -> Bool {
    let object = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
    return object?["kind"] as? String == "screenshot"
}

@Test func screenshotEncoderWritesExactlyTheFixtureLines() throws {
    let encoded = try fixtureScreenshots.map { String(decoding: try $0.jsonLine(), as: UTF8.self) }
    #expect(encoded == (try fixtureLines().filter(isScreenshotLine)))
}

@Test func fixtureCoversEveryScreenshotStatus() {
    #expect(Set(fixtureScreenshots.map(\.status)) == Set(ScreenshotRecord.Status.allCases))
}

@Test func aScreenshotRecordNamesItsCaptureAndCarriesItsTimeAppAndTitle() {
    let capture = fixtureRecords[2]
    let record = ScreenshotRecord.failed(of: capture)
    #expect(record.captureID == capture.id)
    #expect(record.capturedAt == capture.capturedAt)
    #expect(record.appName == "Notion")
    #expect(record.bundleID == "notion.id")
    #expect(record.windowTitle == "M2 plan")
    #expect(record.id != capture.id)
}

@Test func skippedScreenshotsCarryNoImageOrText() {
    for record in [ScreenshotRecord.secureField(of: earlierCapture), .noPermission(of: earlierCapture), .failed(of: earlierCapture)] {
        #expect(record.imagePath == nil && record.imageBytes == nil && record.perceptualHash == nil)
        #expect(record.text == nil && record.textSHA256 == nil && record.textCutOff == nil)
        #expect(record.fullTextBytes == nil)
    }
}

@Test func onlyAKeptScreenshotCarriesTheImageSize() {
    #expect(fixtureScreenshots.filter { $0.imageBytes != nil }.map(\.status) == [.kept])
}

@Test func recognizedTextIsCutOffWhenTheFullTextIsLongerAndHashed() {
    let record = ScreenshotRecord.duplicate(
        of: earlierCapture, imagePath: "screenshots/a.jpg", perceptualHash: "00", text: "abc", fullTextBytes: 17
    )
    #expect(record.textCutOff == true)
    #expect(record.textSHA256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    let whole = ScreenshotRecord.kept(
        of: earlierCapture, imagePath: "screenshots/a.jpg", imageBytes: 1, perceptualHash: "00",
        text: "naïve ✓", fullTextBytes: 7
    )
    #expect(whole.fullTextBytes == 10)
    #expect(whole.textCutOff == false)
}
