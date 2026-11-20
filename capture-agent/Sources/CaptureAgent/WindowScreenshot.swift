import CoreGraphics
import Foundation
import ScreenCaptureKit

/// Takes a still of the application's focused window through ScreenCaptureKit, giving up after the timeout.
func captureFocusedWindow(of processIdentifier: pid_t, title: String?, timeout: TimeInterval = 2) -> WindowImage {
    let result = WindowImageResult()
    SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: true) { content, error in
        guard let content else { return result.finish(error.map(windowImage(for:)) ?? .failed) }
        guard let window = focusedWindow(in: content.windows, of: processIdentifier, title: title) else {
            return result.finish(.failed)
        }
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let configuration = SCStreamConfiguration()
        configuration.width = max(1, Int(window.frame.width * CGFloat(filter.pointPixelScale)))
        configuration.height = max(1, Int(window.frame.height * CGFloat(filter.pointPixelScale)))
        configuration.showsCursor = false
        SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) { image, error in
            result.finish(image.map(WindowImage.image) ?? error.map(windowImage(for:)) ?? .failed)
        }
    }
    return result.wait(timeout: timeout)
}

private func focusedWindow(in windows: [SCWindow], of processIdentifier: pid_t, title: String?) -> SCWindow? {
    let candidates = windows.filter { $0.owningApplication?.processID == processIdentifier && $0.windowLayer == 0 && $0.isOnScreen }
    let order = frontToBackWindowIDs()
    let frontFirst = candidates.sorted { (order[$0.windowID] ?? .max) < (order[$1.windowID] ?? .max) }
    return frontFirst.first { title != nil && $0.title == title } ?? frontFirst.first
}

private func frontToBackWindowIDs() -> [CGWindowID: Int] {
    let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[CFString: Any]] ?? []
    var order: [CGWindowID: Int] = [:]
    for (index, info) in list.enumerated() {
        if let id = info[kCGWindowNumber] as? CGWindowID { order[id] = order[id] ?? index }
    }
    return order
}

private func windowImage(for error: any Error) -> WindowImage {
    let error = error as NSError
    return error.domain == SCStreamErrorDomain && error.code == SCStreamError.Code.userDeclined.rawValue ? .noPermission : .failed
}

private final class WindowImageResult: @unchecked Sendable {
    private let lock = NSLock()
    private let done = DispatchSemaphore(value: 0)
    private var image: WindowImage?

    func finish(_ image: WindowImage) {
        lock.withLock { self.image = self.image ?? image }
        done.signal()
    }

    func wait(timeout: TimeInterval) -> WindowImage {
        guard done.wait(timeout: .now() + timeout) == .success else { return .failed }
        return lock.withLock { image ?? .failed }
    }
}
