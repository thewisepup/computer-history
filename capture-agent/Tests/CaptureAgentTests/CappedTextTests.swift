import Testing
@testable import CaptureAgent

func capped(_ pieces: [String], capBytes: Int) -> CappedText {
    var text = CappedText(capBytes: capBytes)
    pieces.forEach { text.append($0) }
    return text
}

@Test func joinsPiecesWithNewlinesUnderTheCap() {
    let text = capped(["one", "two"], capBytes: 7)
    #expect(text.text == "one\ntwo")
    #expect(text.fullLength == 7)
    #expect(!text.cutOff)
}

@Test func cutsOnACharacterBoundary() {
    let text = capped(["ab👍🏽"], capBytes: 6)
    #expect(text.text == "ab")
    #expect(text.keptBytes == 2)
    #expect(text.cutOff)
    #expect(text.fullLength == "ab👍🏽".utf8.count)
}

@Test func cutsMultibyteTextWithinTheCap() {
    let text = capped(["héllo wörld"], capBytes: 7)
    #expect(text.text == "héllo ")
    #expect(text.text.utf8.count <= 7)
}

@Test func dropsATrailingSeparatorAtTheCap() {
    let text = capped(["abc", "def"], capBytes: 4)
    #expect(text.text == "abc")
    #expect(text.cutOff)
    #expect(text.fullLength == 7)
}

@Test func keepsCountingAfterTheCap() {
    let text = capped(["abcd", "efgh", "ijkl"], capBytes: 4)
    #expect(text.text == "abcd")
    #expect(text.fullLength == 14)
    #expect(text.pieces == 3)
}
