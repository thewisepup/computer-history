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

    /// A kept screenshot as the memory holds it: its image path, thumbnail, capture time and recognized text once known.
    struct KeptFrame {
        let imagePath: String
        let thumbnail: FrameThumbnail
        let keptAt: Date
        let text: KeptText
    }

    let changePercent: Double
    let keepAfter: TimeInterval
    private var seen: [Entry] = []

    init(changePercent: Double, keepAfter: TimeInterval) {
        self.changePercent = changePercent
        self.keepAfter = keepAfter
    }

    /// Marks the window as just seen and returns its last kept frame if that is recent enough and the frame changed fewer pixels than the threshold.
    mutating func see(_ frame: FrameThumbnail, in window: Window, at time: Date) -> KeptFrame? {
        guard let index = seen.firstIndex(where: { $0.window == window }) else { return nil }
        let entry = seen.remove(at: index)
        seen.append(entry)
        guard time.timeIntervalSince(entry.kept.keptAt) <= keepAfter,
              let changed = frame.changedPixels(from: entry.kept.thumbnail, tolerance: Self.pixelTolerance),
              Double(changed) * 100 < changePercent * Double(frame.pixels.count)
        else { return nil }
        return entry.kept
    }

    /// Makes the frame the window's last kept one, forgetting the least recently seen window past the limit.
    mutating func remember(_ kept: KeptFrame, for window: Window) {
        seen.removeAll { $0.window == window }
        seen.append(Entry(window: window, kept: kept))
        if seen.count > Self.windows { seen.removeFirst() }
    }

    private struct Entry {
        let window: Window
        let kept: KeptFrame
    }
}
