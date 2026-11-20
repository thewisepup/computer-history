import CoreGraphics
import Foundation
import ScreenCaptureKit

/// What asking for a picture of the focused window came to: the picture with the ScreenCaptureKit id of the window it shows, or the reason there is none.
public enum WindowImage: Sendable {
    case image(CGImage, windowID: CGWindowID)
    case noPermission
    case failed
}

/// The window to photograph: its app's process, its title, and its frame in screen points from the accessibility tree.
public struct FocusedWindow: Equatable, Sendable {
    public let processIdentifier: pid_t
    public let title: String?
    public let frame: CGRect
}

struct WindowCandidate: Equatable {
    let id: CGWindowID
    let processIdentifier: pid_t
    let frame: CGRect
    let title: String?
}

/// The one on-screen window of the focused window's app whose frame matches it, using the title only to choose among windows with the same frame.
func matchWindow(_ focused: FocusedWindow, among candidates: [WindowCandidate]) -> CGWindowID? {
    let framed = candidates.filter { $0.processIdentifier == focused.processIdentifier && sameFrame($0.frame, focused.frame) }
    if framed.count == 1 { return framed[0].id }
    let titled = framed.filter { focused.title != nil && $0.title == focused.title }
    return titled.count == 1 ? titled[0].id : nil
}

/// The pixel size to ask for: the window's native size, scaled down so its long edge is at most the given one.
func captureSize(of points: CGSize, pixelScale: Double, longEdge: Int) -> (width: Int, height: Int) {
    let width = points.width * pixelScale
    let height = points.height * pixelScale
    let scale = min(1, Double(longEdge) / max(width, height, 1))
    return (max(1, Int((width * scale).rounded())), max(1, Int((height * scale).rounded())))
}

private func sameFrame(_ a: CGRect, _ b: CGRect) -> Bool {
    [a.minX - b.minX, a.minY - b.minY, a.width - b.width, a.height - b.height].allSatisfy { abs($0) <= 2 }
}

/// Takes a still of the focused window through ScreenCaptureKit, answering once with the image or the reason there is none.
func captureFocusedWindow(_ focused: FocusedWindow, longEdge: Int, answer: @escaping @Sendable (WindowImage) -> Void) {
    SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: true) { content, error in
        guard let content else { return answer(error.map(windowImage(for:)) ?? .failed) }
        let windows = content.windows.filter(\.isOnScreen)
        let candidates = windows.map {
            WindowCandidate(id: $0.windowID, processIdentifier: $0.owningApplication?.processID ?? -1, frame: $0.frame, title: $0.title)
        }
        guard let id = matchWindow(focused, among: candidates), let window = windows.first(where: { $0.windowID == id }) else {
            return answer(.failed)
        }
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let configuration = SCStreamConfiguration()
        let size = captureSize(of: window.frame.size, pixelScale: Double(filter.pointPixelScale), longEdge: longEdge)
        configuration.width = size.width
        configuration.height = size.height
        configuration.showsCursor = false
        SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) { image, error in
            answer(image.map { .image($0, windowID: id) } ?? error.map(windowImage(for:)) ?? .failed)
        }
    }
}

private func windowImage(for error: any Error) -> WindowImage {
    let error = error as NSError
    return error.domain == SCStreamErrorDomain && error.code == SCStreamError.Code.userDeclined.rawValue ? .noPermission : .failed
}
