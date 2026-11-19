import Foundation
import Testing
@testable import CaptureAgent

@Test func encoderWritesExactlyTheFixtureLines() throws {
    let encoded = try fixtureRecords.map { String(decoding: try $0.jsonLine(), as: UTF8.self) }
    #expect(encoded == (try fixtureLines()))
}

@Test func fixtureCoversEveryKindAndTrigger() {
    #expect(Set(fixtureRecords.map(\.kind)) == Set(SpoolRecord.Kind.allCases))
    #expect(Set(fixtureRecords.compactMap(\.trigger)) == Set(SpoolRecord.Trigger.allCases))
}

@Test func recordsWithoutTextCarryNoTitle() {
    for record in fixtureRecords where record.kind != .capture {
        #expect(record.windowTitle == nil)
        #expect(record.text == nil)
    }
}

@Test func fullTextBytesIsNeverLessThanTheText() throws {
    let record = SpoolRecord.capture(
        at: utc("2026-11-18T09:00:00.000Z"), trigger: .app, appName: "Notes", bundleID: nil,
        windowTitle: nil, text: "naïve ✓", fullTextBytes: 7, timedOut: false
    )
    #expect(record.fullTextBytes == 10)
    #expect(String(decoding: try record.jsonLine(), as: UTF8.self).contains("\"text_cut_off\":false"))
}
