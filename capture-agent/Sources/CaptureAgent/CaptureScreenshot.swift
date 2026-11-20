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

    func take(for capture: SpoolRecord, of application: FocusedApplication) -> ScreenshotRecord {
        switch focusedField(in: mac.applicationElement(application.processIdentifier)) {
        case .password: return .secureField(of: capture)
        case .unknown: return .failed(of: capture)
        case .other: break
        }
        switch mac.focusedWindowImage(application, title: capture.windowTitle) {
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
}
