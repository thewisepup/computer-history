import Foundation

/// Everything the capture loop asks of the Mac: the clocks, the user's presence, the Accessibility grant, the focused and frontmost apps, the accessibility tree and whether its bundle ships Electron.
public protocol Mac {
    associatedtype Element: AccessibilityElement

    func uptime() -> TimeInterval
    func now() -> Date
    func sleep(_ seconds: TimeInterval)
    func samplePresence() -> Presence
    func accessibilityTrusted() -> Bool
    func focusedApplication() -> FocusedApplication?
    func frontmostApplication() -> FocusedApplication?
    func applicationElement(_ processIdentifier: pid_t) -> Element
    func hasElectronFramework(_ bundle: URL) -> Bool
}

/// The real Mac: system uptime and time, presence from macOS, and the live accessibility API.
public struct LiveMac: Mac, Sendable {
    private let presence = LivePresence()
    private let frontmost = LiveFrontmostApplication()

    /// Sets every accessibility call this process makes to time out after the given seconds, and starts listening for sleep, wake and app activations.
    public init(callTimeout: TimeInterval) {
        LiveAccessibilityElement.setProcessCallTimeout(callTimeout)
    }

    public func uptime() -> TimeInterval { ProcessInfo.processInfo.systemUptime }
    public func now() -> Date { Date() }
    public func sleep(_ seconds: TimeInterval) { Thread.sleep(forTimeInterval: seconds) }
    public func samplePresence() -> Presence { presence.sample() }
    public func accessibilityTrusted() -> Bool { isAccessibilityTrusted(prompt: false) }
    public func focusedApplication() -> FocusedApplication? { CaptureAgent.focusedApplication(orFrontmost: frontmost.application) }
    public func frontmostApplication() -> FocusedApplication? { frontmost.application() }

    public func applicationElement(_ processIdentifier: pid_t) -> LiveAccessibilityElement {
        LiveAccessibilityElement.application(processIdentifier)
    }

    public func hasElectronFramework(_ bundle: URL) -> Bool { bundleHasElectronFramework(bundle) }
}
