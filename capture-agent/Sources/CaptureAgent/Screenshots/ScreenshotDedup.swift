import CoreGraphics
import Foundation

/// Remembers the last kept screenshot of each of the most recently seen windows.
struct ScreenshotDedup {
    static let windows = 12
    static let pixelTolerance = 24

    /// A window as the memory tells windows apart: the ScreenCaptureKit id of the window photographed, and its title.
    struct Window: Equatable {
        let id: CGWindowID
        let title: String?
    }

    /// A kept screenshot as the memory holds it: its image path, thumbnail, capture time and recognized text once known.
    struct KeptScreenshot {
        let imagePath: String
        let thumbnail: ScreenshotThumbnail
        let keptAt: Date
        let text: KeptText
    }

    let changePixels: Int
    let keepAfter: TimeInterval
    private var seen: [Entry] = []

    init(changePixels: Int, keepAfter: TimeInterval) {
        self.changePixels = changePixels
        self.keepAfter = keepAfter
    }

    /// Marks the window as just seen and returns its last kept screenshot if that was kept in the last keepAfter seconds and the new one changed fewer pixels than the threshold.
    mutating func see(_ thumbnail: ScreenshotThumbnail, in window: Window, at time: Date) -> KeptScreenshot? {
        guard let index = seen.firstIndex(where: { $0.window == window }) else { return nil }
        let entry = seen.remove(at: index)
        seen.append(entry)
        guard (0...keepAfter).contains(time.timeIntervalSince(entry.kept.keptAt)),
              let changed = thumbnail.changedPixels(from: entry.kept.thumbnail, tolerance: Self.pixelTolerance),
              changed < changePixels
        else { return nil }
        return entry.kept
    }

    /// Makes the screenshot the window's last kept one, forgetting the least recently seen window past the limit.
    mutating func remember(_ kept: KeptScreenshot, for window: Window) {
        seen.removeAll { $0.window == window }
        seen.append(Entry(window: window, kept: kept))
        if seen.count > Self.windows { seen.removeFirst() }
    }

    private struct Entry {
        let window: Window
        let kept: KeptScreenshot
    }
}
