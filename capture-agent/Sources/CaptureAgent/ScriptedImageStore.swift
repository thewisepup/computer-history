import CoreGraphics
import Foundation

/// Saves pictures through another store and reads back, for each saved file, the scripted recognized text of the window focused when it was saved.
final class ScriptedImageStore: ImageStore, @unchecked Sendable {
    private let images: any ImageStore
    private let mac: ScriptedMac
    private let texts: [CGWindowID: String]
    private let lock = NSLock()
    private var saved: [URL: String] = [:]

    init(images: any ImageStore, mac: ScriptedMac, texts: [CGWindowID: String]) {
        self.images = images
        self.mac = mac
        self.texts = texts
    }

    func save(_ image: CGImage, id: UUID, at date: Date) throws -> SavedImage {
        let file = try images.save(image, id: id, at: date)
        let window = mac.focused.flatMap { mac.apps[$0.processIdentifier]?.focusedWindow }
        let text = window.flatMap { texts[$0.windowID] } ?? ""
        lock.withLock { saved[file.file] = text }
        return file
    }

    func recognizedText(inImageAt file: URL) -> String {
        lock.withLock { saved[file] ?? "" }
    }
}
