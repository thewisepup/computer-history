import Foundation
import Testing
@testable import CaptureAgent

@Test func formatsUTCMilliseconds() {
    let time = SpoolTime(utc("2026-11-18T09:00:31.007Z"))
    #expect(time.iso8601 == "2026-11-18T09:00:31.007Z")
    #expect(time.fileStamp == "20261118T090031.007Z")
}

@Test func readsBackItsOwnFileStamp() {
    let time = SpoolTime(utc("2026-02-28T23:59:59.999Z"))
    #expect(SpoolTime(fileStamp: time.fileStamp) == time)
}

@Test(arguments: ["open", "20261118T090031Z", "20261118T090031.07Z", "20261318T090031.007Z", "20261118T090031.007Z.jsonl"])
func rejectsOtherNames(name: String) {
    #expect(SpoolTime(fileStamp: name) == nil)
}
