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
    let record = captureRecord(text: "naïve ✓", fullTextBytes: 7)
    #expect(record.fullTextBytes == 10)
    #expect(record.textCutOff == false)
    #expect(String(decoding: try record.jsonLine(), as: UTF8.self).contains("\"text_cut_off\":false"))
}

@Test func aCaptureIsCutOffWhenTheFullTextIsLonger() {
    #expect(captureRecord(text: "abcdef\ngh", fullTextBytes: 17).textCutOff == true)
    #expect(captureRecord(text: "abc", fullTextBytes: 3).textCutOff == false)
}

@Test func aCaptureHashesItsText() {
    #expect(captureRecord(text: "abcdef\ngh", fullTextBytes: 17).textSHA256 == "b2e67bb70831a96b11c69ab98469b043f19df1b3bed8b014ac461872b0adcf3d")
    #expect(captureRecord(text: "abc", fullTextBytes: 3).textSHA256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
}

@Test func recordsWithoutTextHaveNoHashOrCutOff() {
    for record in fixtureRecords where record.kind != .capture {
        #expect(record.textSHA256 == nil)
        #expect(record.textCutOff == nil)
    }
}
