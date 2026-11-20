import Foundation
import Testing
@testable import CaptureAgent

struct RecognitionError: Error, CustomStringConvertible {
    var description: String { "vision broke" }
}

/// Recognizes each image as "text of <record id>", but only once let go or after a minute.
final class HeldRecognizer: @unchecked Sendable {
    private let gate = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var started = 0

    var calls: Int { lock.withLock { started } }

    func text(_ image: URL) -> String {
        lock.withLock { started += 1 }
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

@Test func eachKindOfFailureKeepsItsOwnLastError() throws {
    let fixture = LoopFixture()
    fixture.mac.recognizedText = { _ in throw RecognitionError() }
    fixture.screenshotGate.refusals = 1
    fixture.run(for: 2)
    #expect(fixture.counts.take().description.hasSuffix(
        ", 1 screenshot records failed to write (last: spool refused), 1 text recognitions failed (last: vision broke)"
    ))
}

@Test func aHungRecognitionCostsOnlyItsTimeoutAndLaterKeptFramesGetEmptyTextUntilItAnswers() throws {
    let fixture = LoopFixture()
    fixture.screenshots.recognitionTimeout = 0.05
    let recognizer = HeldRecognizer()
    fixture.mac.recognizedText = recognizer.text
    var seed = 1
    fixture.mac.windowImage = { _, _ in .image(fixtureImage(width: 1600, height: 1000, seed: seed), windowID: 1) }
    fixture.run(for: 2)
    seed = 2
    fixture.run(for: 30)
    #expect(try fixture.statuses() == ["kept", "kept"])
    #expect(try fixture.screenshotRecords().map { $0["text"] as? String } == ["", ""])
    #expect(recognizer.calls == 1)
    #expect(fixture.counts.take().recognitionsFailed == 2)
    recognizer.letGo()
    var shots: [[String: Any]] = []
    for attempt in 3..<40 where shots.last?["text"] as? String ?? "" == "" {
        seed = attempt
        fixture.run(for: 30)
        shots = try fixture.screenshotRecords()
    }
    let last = try #require(shots.last)
    #expect(last["status"] as? String == "kept")
    #expect(last["text"] as? String == "text of \(last["id"] as! String)")
}

@Test func theMinuteLineSaysHowManyScreenshotRecordsAreQueued() throws {
    let fixture = LoopFixture()
    let recognizer = HeldRecognizer()
    fixture.mac.recognizedText = recognizer.text
    fixture.run(for: 100, waitingForScreenshots: false)
    let captures = try fixture.kinds().count
    #expect(fixture.counts.take().description.contains(", \(captures) screenshot records queued"))
    recognizer.letGo()
    fixture.waitForScreenshots()
    #expect(fixture.counts.take().description.contains(", 0 screenshot records queued"))
}

@Test func aWindowWhoseKeptFrameGotNoTextKeepsItsNextFrameAndReadsIt() throws {
    let fixture = LoopFixture()
    let failing = LockedFlag(true)
    fixture.mac.recognizedText = { image in
        if failing.value { throw RecognitionError() }
        return "text of \(image.deletingPathExtension().lastPathComponent)"
    }
    fixture.run(for: 2)
    failing.value = false
    fixture.run(for: 60)
    #expect(try fixture.statuses() == ["kept", "kept", "duplicate"])
    let shots = try fixture.screenshotRecords()
    let read = "text of \(shots[1]["id"] as! String)"
    #expect(shots.map { $0["text"] as? String } == ["", read, read])
}

final class LockedFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var current: Bool

    init(_ value: Bool) {
        current = value
    }

    var value: Bool {
        get { lock.withLock { current } }
        set { lock.withLock { current = newValue } }
    }
}

/// Reads the first image once started, then holds every later one until let go; each waits a minute at most.
final class FirstThenHeldRecognizer: @unchecked Sendable {
    private let lock = NSLock()
    private var calls = 0
    private let first = DispatchSemaphore(value: 0)
    private let held = HeldRecognizer()

    func text(_ image: URL) -> String {
        let call = lock.withLock {
            calls += 1
            return calls
        }
        guard call > 1 else {
            _ = first.wait(timeout: .now() + 60)
            return "first"
        }
        return held.text(image)
    }

    func startFirst() {
        first.signal()
    }

    func letGo() {
        held.letGo()
    }
}

@Test func stoppingWritesWhatTheDeadlineAllowsAndNothingAfterIt() throws {
    let fixture = LoopFixture()
    fixture.screenshots.recognitionTimeout = 60
    let recognizer = FirstThenHeldRecognizer()
    fixture.mac.recognizedText = recognizer.text
    var seed = 1
    fixture.mac.windowImage = { _, _ in .image(fixtureImage(width: 1600, height: 1000, seed: seed), windowID: 1) }
    for next in 2...4 {
        fixture.run(for: 30, waitingForScreenshots: false)
        seed = next
    }
    let captures = try fixture.kinds().count
    recognizer.startFirst()
    let dropped = fixture.loop.stopScreenshots(by: .now() + 1)
    #expect(try fixture.screenshotRecords().map { $0["text"] as? String } == ["first"])
    #expect(dropped == captures - 1)
    recognizer.letGo()
    fixture.waitForScreenshots()
    #expect(try fixture.screenshotRecords().count == 1)
    #expect(fixture.counts.take().description.contains(", 0 screenshot records queued"))
}
