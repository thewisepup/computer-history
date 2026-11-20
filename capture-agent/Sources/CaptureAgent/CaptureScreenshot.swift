import Foundation

/// Whether captures take screenshots, the long edge in pixels and JPEG quality of the images kept, how many thumbnail pixels must change for a new image, and the seconds after which an unchanged window gets one anyway.
public struct ScreenshotSettings: Equatable, Sendable {
    public var enabled: Bool
    public var longEdge: Int
    public var quality: Int
    public var changePixels: Int
    public var keepAfter: TimeInterval

    public init(
        enabled: Bool = true, longEdge: Int = 1440, quality: Int = 60, changePixels: Int = 6, keepAfter: TimeInterval = 600
    ) {
        self.enabled = enabled
        self.longEdge = longEdge
        self.quality = quality
        self.changePixels = changePixels
        self.keepAfter = keepAfter
    }
}

/// A screenshot record waiting for the spool: ready as it is, waiting on its own image's text, or copying a kept screenshot's text.
enum QueuedScreenshot: Sendable {
    case ready(ScreenshotRecord)
    case recognize(ScreenshotRecord, image: URL, into: KeptText)
    case copy(ScreenshotRecord, from: KeptText)
}

/// Takes the screenshot that goes with a capture just written and turns it into the capture's screenshot record.
struct CaptureScreenshot<M: Mac> {
    let mac: M
    let images: any ImageStore
    let longEdge: Int
    let pause: PauseSwitch
    let idleThreshold: TimeInterval
    var dedup: FrameDedup

    mutating func take(for capture: SpoolRecord, of application: FocusedApplication) -> QueuedScreenshot {
        guard !pause.isPaused, mac.samplePresence().silence(idleThreshold: idleThreshold).isEmpty,
              mac.focusedApplication()?.processIdentifier == application.processIdentifier
        else { return .ready(.failed(of: capture)) }
        let app = mac.applicationElement(application.processIdentifier)
        switch focusedField(in: app) {
        case .password: return .ready(.secureField(of: capture))
        case .unknown: return .ready(.failed(of: capture))
        case .other: break
        }
        guard case .value(let window) = app.element("AXFocusedWindow"), has(window, title: capture.windowTitle),
              case .value(let frame) = window.frame()
        else { return .ready(.failed(of: capture)) }
        let focused = FocusedWindow(processIdentifier: application.processIdentifier, title: capture.windowTitle, frame: frame)
        switch mac.focusedWindowImage(focused, longEdge: longEdge) {
        case .noPermission:
            return .ready(.noPermission(of: capture))
        case .failed:
            return .ready(.failed(of: capture))
        case .image(let image, let windowID):
            guard let hash = differenceHash(image), let frame = FrameThumbnail(image, points: focused.frame.size) else {
                return .ready(.failed(of: capture))
            }
            let window = FrameDedup.Window(id: windowID, title: capture.windowTitle)
            if let kept = dedup.see(frame, in: window, at: capture.capturedAt) {
                let duplicate = ScreenshotRecord.duplicate(
                    of: capture, imagePath: kept.imagePath, perceptualHash: hash.hex, text: "", fullTextBytes: 0
                )
                return .copy(duplicate, from: kept.text)
            }
            let id = UUID()
            guard let saved = try? images.save(image, id: id, at: capture.capturedAt) else { return .ready(.failed(of: capture)) }
            let text = KeptText()
            dedup.remember(
                FrameDedup.KeptFrame(imagePath: saved.path, thumbnail: frame, keptAt: capture.capturedAt, text: text), for: window
            )
            let kept = ScreenshotRecord.kept(
                id: id, of: capture, imagePath: saved.path, imageBytes: saved.bytes, perceptualHash: hash.hex, text: "", fullTextBytes: 0
            )
            return .recognize(kept, image: saved.file, into: text)
        }
    }

    private func has(_ window: M.Element, title: String?) -> Bool {
        switch window.string("AXTitle") {
        case .value(let current): current == title
        case .missing: title == nil
        case .timedOut: false
        }
    }
}
