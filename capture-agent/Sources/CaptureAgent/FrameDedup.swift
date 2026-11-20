import CoreGraphics
import Foundation

/// Remembers the last kept frame of each of the most recently seen windows.
struct FrameDedup {
    static let windows = 12
    static let pixelTolerance = 24

    /// A window as the memory tells windows apart: the ScreenCaptureKit id of the window photographed, and its title.
    struct Window: Equatable {
        let id: CGWindowID
        let title: String?
    }

    /// A kept screenshot as the memory holds it: its record id, image path, thumbnail, capture time and recognized text.
    struct KeptFrame: Equatable {
        let recordID: UUID
        let imagePath: String
        let thumbnail: FrameThumbnail
        let keptAt: Date
        let text: String
        let fullTextBytes: Int
    }

    let changePixels: Int
    let keepAfter: TimeInterval
    private var seen: [Entry] = []

    init(changePixels: Int, keepAfter: TimeInterval) {
        self.changePixels = changePixels
        self.keepAfter = keepAfter
    }

    /// Marks the window as just seen and returns its last kept frame if that was kept in the last keepAfter seconds and the frame changed fewer pixels than the threshold.
    mutating func see(_ frame: FrameThumbnail, in window: Window, at time: Date) -> KeptFrame? {
        guard let index = seen.firstIndex(where: { $0.window == window }) else { return nil }
        let entry = seen.remove(at: index)
        seen.append(entry)
        guard (0...keepAfter).contains(time.timeIntervalSince(entry.kept.keptAt)),
              let changed = frame.changedPixels(from: entry.kept.thumbnail, tolerance: Self.pixelTolerance),
              changed < changePixels
        else { return nil }
        return entry.kept
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
