import Foundation

/// Whether captures take screenshots, and the long edge in pixels and JPEG quality of the images kept.
public struct ScreenshotSettings: Equatable, Sendable {
    public var enabled: Bool
    public var longEdge: Int
    public var quality: Int

    public init(enabled: Bool = true, longEdge: Int = 1440, quality: Int = 60) {
        self.enabled = enabled
        self.longEdge = longEdge
        self.quality = quality
    }
}

/// Takes the screenshot that goes with a capture just written and turns it into the capture's screenshot record.
struct CaptureScreenshot<M: Mac> {
    let mac: M
    let images: any ImageStore
    let longEdge: Int
    let pause: PauseSwitch
    let idleThreshold: TimeInterval

    func take(for capture: SpoolRecord, of application: FocusedApplication) -> ScreenshotRecord {
        guard !pause.isPaused, mac.samplePresence().silence(idleThreshold: idleThreshold).isEmpty,
              mac.focusedApplication()?.processIdentifier == application.processIdentifier
        else { return .failed(of: capture) }
        let app = mac.applicationElement(application.processIdentifier)
        switch focusedField(in: app) {
        case .password: return .secureField(of: capture)
        case .unknown: return .failed(of: capture)
        case .other: break
        }
        guard case .value(let window) = app.element("AXFocusedWindow"), has(window, title: capture.windowTitle),
              case .value(let frame) = window.frame()
        else { return .failed(of: capture) }
        let focused = FocusedWindow(processIdentifier: application.processIdentifier, title: capture.windowTitle, frame: frame)
        switch mac.focusedWindowImage(focused, longEdge: longEdge) {
        case .noPermission:
            return .noPermission(of: capture)
        case .failed:
            return .failed(of: capture)
        case .image(let image):
            let id = UUID()
            guard let hash = differenceHash(image), let saved = try? images.save(image, id: id, at: capture.capturedAt) else {
                return .failed(of: capture)
            }
            return .kept(
                id: id, of: capture, imagePath: saved.path, imageBytes: saved.bytes, perceptualHash: hash, text: "", fullTextBytes: 0
            )
        }
    }

    /// Deletes the image a kept record names, for a record that never reached the spool.
    func discard(_ record: ScreenshotRecord) {
        if record.status == .kept, let path = record.imagePath { images.remove(path) }
    }

    private func has(_ window: M.Element, title: String?) -> Bool {
        switch window.string("AXTitle") {
        case .value(let current): current == title
        case .missing: title == nil
        case .timedOut: false
        }
    }
}
