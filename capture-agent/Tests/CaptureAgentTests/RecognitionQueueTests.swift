import Foundation
import Testing
@testable import CaptureAgent

struct RecognitionError: Error, CustomStringConvertible {
    var description: String { "vision broke" }
}

/// Recognizes each image as "text of <record id>", but only once let go or after a minute.
final class HeldRecognizer: @unchecked Sendable {
    private let gate = DispatchSemaphore(value: 0)

    func text(_ image: URL) -> String {
        _ = gate.wait(timeout: .now() + 60)
        gate.signal()
        return "text of \(image.deletingPathExtension().lastPathComponent)"
    }

    func letGo() {
        gate.signal()
    }
}

@Test func aSlowRecognitionNeverHoldsUpTheCaptureRecords() throws {
    let fixture = LoopFixture()
    let recognizer = HeldRecognizer()
    fixture.mac.recognizedText = recognizer.text
    fixture.run(for: 100, waitingForScreenshots: false)
    let captures = try fixture.kinds()
    #expect(captures.count >= 3)
    #expect(try fixture.screenshotRecords().isEmpty)
    recognizer.letGo()
    fixture.waitForScreenshots()
    #expect(try fixture.screenshotRecords().count == captures.count)
}

@Test func screenshotRecordsReachTheSpoolInCaptureOrderWithTheirCaptureTimes() throws {
    let fixture = LoopFixture()
    let recognizer = HeldRecognizer()
    fixture.mac.recognizedText = recognizer.text
    let app = fixture.mac.apps[plainApp.processIdentifier]!
    fixture.run(for: 2, waitingForScreenshots: false)
    app.focusedElement = fixture.mac.node("password", role: "AXTextField", ["AXSubrole": "AXSecureTextField"])
    fixture.run(for: 30, waitingForScreenshots: false)
    app.focusedElement = nil
    fixture.mac.focused = chrome
    fixture.run(for: 3, waitingForScreenshots: false)
    fixture.mac.focused = plainApp
    fixture.run(for: 3, waitingForScreenshots: false)
    fixture.mac.windowImage = { _, _ in .failed }
    fixture.mac.focused = chrome
    fixture.run(for: 3, waitingForScreenshots: false)
    recognizer.letGo()
    fixture.waitForScreenshots()
    #expect(try fixture.statuses() == ["kept", "secure-field", "kept", "duplicate", "failed"])
    let shots = try fixture.screenshotRecords()
    let captures = try fixture.withoutScreenshots()
    #expect(shots.map { $0["capture_id"] as! String } == captures.map { $0["id"] as! String })
    #expect(shots.map { $0["captured_at"] as! String } == captures.map { $0["captured_at"] as! String })
    #expect(shots[0]["text"] as? String == "text of \(shots[0]["id"] as! String)")
    #expect(shots[2]["text"] as? String == "text of \(shots[2]["id"] as! String)")
}

@Test func duplicatesQueuedWhileTheirKeptFrameIsRecognizedCopyItsFinishedText() throws {
    let fixture = LoopFixture()
    let recognizer = HeldRecognizer()
    fixture.mac.recognizedText = recognizer.text
    fixture.run(for: 100, waitingForScreenshots: false)
    recognizer.letGo()
    fixture.waitForScreenshots()
    let shots = try fixture.screenshotRecords()
    try #require(shots.count >= 3)
    #expect(try fixture.statuses() == ["kept"] + Array(repeating: "duplicate", count: shots.count - 1))
    let kept = shots[0]
    #expect(kept["text"] as? String == "text of \(kept["id"] as! String)")
    for duplicate in shots.dropFirst() {
        for key in ["image_path", "text", "text_sha256", "full_text_bytes", "text_cut_off"] {
            #expect(duplicate[key] as? NSObject == kept[key] as? NSObject, "\(key)")
        }
    }
}

@Test func recognizedTextIsCutAtTheWindowTextCapAndDuplicatesCopyTheCut() throws {
    let fixture = LoopFixture()
    fixture.windowText = WindowTextSettings(textCapBytes: 8)
    fixture.mac.recognizedText = { _ in "héllo wörld" }
    fixture.run(for: 40)
    let shots = try fixture.screenshotRecords()
    #expect(try fixture.statuses() == ["kept", "duplicate"])
    for shot in shots {
        #expect(shot["text"] as? String == "héllo w")
        #expect(shot["full_text_bytes"] as? Int == 13)
        #expect(shot["text_cut_off"] as? Bool == true)
        #expect(shot["text_sha256"] as? String == sha256Hex("héllo w"))
    }
}

@Test func aFailedRecognitionKeepsTheImageWithEmptyTextAndIsCounted() throws {
    let fixture = LoopFixture()
    fixture.mac.recognizedText = { _ in throw RecognitionError() }
    fixture.run(for: 2)
    let shots = try fixture.screenshotRecords()
    #expect(try fixture.statuses() == ["kept"])
    #expect(shots[0]["text"] as? String == "")
    #expect(shots[0]["full_text_bytes"] as? Int == 0)
    #expect(shots[0]["text_cut_off"] as? Bool == false)
    #expect(savedImages(in: fixture.settings.folder) == ["\(shots[0]["id"] as! String).jpg"])
    let summary = fixture.counts.take()
    #expect(summary.recognitionsFailed == 1)
    #expect(summary.description.hasSuffix(", 1 text recognitions failed (last: vision broke)"))
}

@Test func aKeptRecordTheSpoolRefusesKeepsItsImageAndItsDuplicatesStillPointAtIt() throws {
    let fixture = LoopFixture()
    fixture.mac.recognizedText = { _ in "notes" }
    fixture.screenshotGate.refusals = 1
    fixture.run(for: 70)
    #expect(try fixture.statuses() == ["duplicate", "duplicate"])
    let shots = try fixture.screenshotRecords()
    let path = try #require(shots[0]["image_path"] as? String)
    #expect(shots[1]["image_path"] as? String == path)
    #expect(shots.map { $0["text"] as? String } == ["notes", "notes"])
    #expect(FileManager.default.fileExists(atPath: fixture.settings.folder.appendingPathComponent(path).path))
    #expect(savedImages(in: fixture.settings.folder).count == 1)
    #expect(fixture.counts.take().screenshotsFailed == 1)
}
