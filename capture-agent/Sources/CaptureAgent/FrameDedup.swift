/// Remembers the last kept screenshot of each of the most recently seen windows, a window being an app and a window title.
struct FrameDedup {
    static let windows = 12

    let threshold: Int
    private var kept: [(window: Window, record: ScreenshotRecord)] = []

    init(threshold: Int) {
        self.threshold = threshold
    }

    /// The window's last kept record when at most the threshold of the frame's bits differ from its hash, which also marks the window as just seen.
    mutating func keptMatch(of frame: FrameHash, for capture: SpoolRecord) -> ScreenshotRecord? {
        let window = Window(appName: capture.appName, bundleID: capture.bundleID, title: capture.windowTitle)
        guard let index = kept.firstIndex(where: { $0.window == window }),
              let hash = kept[index].record.perceptualHash.flatMap(FrameHash.init(hex:)),
              hash.distance(to: frame) <= threshold
        else { return nil }
        let match = kept.remove(at: index)
        kept.append(match)
        return match.record
    }

    /// Makes a kept record its window's last kept frame, forgetting the least recently seen window past the limit.
    mutating func remember(_ record: ScreenshotRecord) {
        guard record.status == .kept else { return }
        let window = Window(appName: record.appName, bundleID: record.bundleID, title: record.windowTitle)
        kept.removeAll { $0.window == window }
        kept.append((window, record))
        if kept.count > Self.windows { kept.removeFirst() }
    }

    /// Forgets a kept record whose image is gone.
    mutating func forget(_ record: ScreenshotRecord) {
        kept.removeAll { $0.record.id == record.id }
    }

    private struct Window: Equatable {
        let appName: String?
        let bundleID: String?
        let title: String?
    }
}
