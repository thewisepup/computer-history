import Foundation

/// Whether captures take screenshots, the long edge in pixels and JPEG quality of the images kept, how many thumbnail pixels must change for a new image, the seconds after which an unchanged window gets one anyway, and how long text recognition may take.
public struct ScreenshotSettings: Equatable, Sendable {
    public var enabled: Bool
    public var longEdge: Int
    public var quality: Int
    public var changePixels: Int
    public var keepAfter: TimeInterval
    public var recognitionTimeout: TimeInterval

    public init(
        enabled: Bool = true, longEdge: Int = 1440, quality: Int = 60, changePixels: Int = 6, keepAfter: TimeInterval = 600,
        recognitionTimeout: TimeInterval = 10
    ) {
        self.enabled = enabled
        self.longEdge = longEdge
        self.quality = quality
        self.changePixels = changePixels
        self.keepAfter = keepAfter
        self.recognitionTimeout = recognitionTimeout
    }
}

/// A screenshot record waiting for the spool: ready as it is, or built once its own image's text is read or its kept screenshot's text is known.
enum QueuedScreenshot: Sendable {
    typealias Record = @Sendable ((text: String, fullTextBytes: Int)) -> ScreenshotRecord

    case ready(ScreenshotRecord)
    case recognize(image: URL, into: KeptText, record: Record)
    case copy(from: KeptText, record: Record)
}

/// Takes the screenshot that goes with a capture just written and turns it into the capture's screenshot record, reminding once a day while the Screen Recording grant is missing.
struct CaptureScreenshot<M: Mac> {
    let mac: M
    let images: any ImageStore
    let longEdge: Int
    let pause: PauseSwitch
    let idleThreshold: TimeInterval
    var dedup: ScreenshotDedup
    var reminder: PermissionReminder
    let log: (String) -> Void

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
            reminder.grantMissing(at: mac.now(), post: mac.post, log: log)
            return .ready(.noPermission(of: capture))
        case .failed:
            return .ready(.failed(of: capture))
        case .image(let image, let windowID):
            reminder.grantSeen()
            guard let hash = differenceHash(image), let frame = FrameThumbnail(image, points: focused.frame.size) else {
                return .ready(.failed(of: capture))
            }
            let window = ScreenshotDedup.Window(id: windowID, title: capture.windowTitle)
            if let kept = dedup.see(frame, in: window, at: capture.capturedAt), !kept.text.failed {
                return .copy(from: kept.text) { read in
                    .duplicate(
                        of: capture, imagePath: kept.imagePath, perceptualHash: hash.hex, text: read.text, fullTextBytes: read.fullTextBytes
                    )
                }
            }
            let id = UUID()
            guard let saved = try? images.save(image, id: id, at: capture.capturedAt) else { return .ready(.failed(of: capture)) }
            let text = KeptText()
            dedup.remember(
                ScreenshotDedup.KeptScreenshot(imagePath: saved.path, thumbnail: frame, keptAt: capture.capturedAt, text: text), for: window
            )
            return .recognize(image: saved.file, into: text) { read in
                .kept(
                    id: id, of: capture, imagePath: saved.path, imageBytes: saved.bytes, perceptualHash: hash.hex, text: read.text,
                    fullTextBytes: read.fullTextBytes
                )
            }
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
