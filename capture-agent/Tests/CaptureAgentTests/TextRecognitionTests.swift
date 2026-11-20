import Foundation
import Testing
@testable import CaptureAgent

@Test func visionReadsBothKnownLinesOfAPicture() throws {
    let image = try #require(Bundle.module.url(forResource: "recognized-text", withExtension: "jpg"))
    let started = Date()
    let text = try recognizeText(inImageAt: image)
    print("recognized \(text.utf8.count) bytes in \(String(format: "%.2f", Date().timeIntervalSince(started)))s: \(text.debugDescription)")
    let words = text.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ")
    #expect(words.contains("recognized text stays on this mac"))
    #expect(words.contains("window 42 of the capture agent"))
}

@Test func aFileThatIsNotAPictureFailsRecognition() throws {
    let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID()).jpg")
    try Data("not a picture".utf8).write(to: file)
    defer { try? FileManager.default.removeItem(at: file) }
    #expect(throws: (any Error).self) { try recognizeText(inImageAt: file) }
}
