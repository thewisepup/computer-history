import CoreGraphics
import Foundation

/// Remembers the last kept frame of each of the most recently seen windows.
struct FrameDedup {
    static let windows = 12

    /// A window as the memory tells windows apart: the ScreenCaptureKit id of the window photographed, and its title.
    struct Window: Equatable {
        let id: CGWindowID
        let title: String?
    }

    /// A kept screenshot as the memory holds it: its record id, image path, hash and recognized text.
    struct KeptFrame: Equatable {
        let recordID: UUID
        let imagePath: String
        let hash: FrameHash
        let text: String
        let fullTextBytes: Int
    }

    let threshold: Int
    private var seen: [Entry] = []

    init(threshold: Int) {
        self.threshold = threshold
    }

    /// Marks the window as just seen and returns its last kept frame if at most the threshold of its bits differ from the hash.
    mutating func see(_ hash: FrameHash, in window: Window) -> KeptFrame? {
        guard let index = seen.firstIndex(where: { $0.window == window }) else { return nil }
        let entry = seen.remove(at: index)
        seen.append(entry)
        return entry.kept.hash.distance(to: hash) <= threshold ? entry.kept : nil
    }

    /// Makes the frame the window's last kept one, forgetting the least recently seen window past the limit.
    mutating func remember(_ kept: KeptFrame, for window: Window) {
        let replaced = seen.first { $0.window == window }?.kept
        seen.removeAll { $0.window == window }
        seen.append(Entry(window: window, kept: kept, replaced: replaced))
        if seen.count > Self.windows { seen.removeFirst() }
    }

    /// Forgets a kept frame whose image is gone, giving its window back the kept frame it replaced.
    mutating func forget(_ recordID: UUID) {
        guard let index = seen.firstIndex(where: { $0.kept.recordID == recordID }) else { return }
        let entry = seen.remove(at: index)
        if let replaced = entry.replaced { seen.insert(Entry(window: entry.window, kept: replaced, replaced: nil), at: index) }
    }

    private struct Entry {
        let window: Window
        let kept: KeptFrame
        let replaced: KeptFrame?
    }
}
