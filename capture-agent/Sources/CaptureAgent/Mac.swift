import Foundation

/// Everything the capture loop asks of the Mac: the clocks, the user's presence and its sleep and wake, the Accessibility grant, the focused and frontmost apps, the accessibility tree, whether its bundle ships Electron, a picture of the focused window, and posting a notification.
public protocol Mac {
    associatedtype Element: AccessibilityElement

    func uptime() -> TimeInterval
    func now() -> Date
    func sleep(_ seconds: TimeInterval)
    func samplePresence() -> Presence
    /// Calls the handler, replacing any earlier one, with the time as the Mac goes to sleep and as it wakes.
    func onSleepChange(_ handler: @escaping @Sendable (SleepChange, Date) -> Void)
    func accessibilityTrusted() -> Bool
    func focusedApplication() -> FocusedApplication?
    func frontmostApplication() -> FocusedApplication?
    func applicationElement(_ processIdentifier: pid_t) -> Element
    func hasElectronFramework(_ bundle: URL) -> Bool
    func focusedWindowImage(_ window: FocusedWindow, longEdge: Int) -> WindowImage
    func post(_ notification: UserNotification, shownLater: @escaping @Sendable () -> Void) -> NotificationPosting
}

/// The real Mac: system uptime and time, presence from macOS, the live accessibility API, pictures of the focused window through ScreenCaptureKit, and notifications through the notification centre.
public struct LiveMac: Mac, Sendable {
    private let presence = LivePresence()
    private let frontmost = LiveFrontmostApplication()
    private let screenshots = OneRequestAtATime()
    private let notifications = LiveNotifications()

    /// Sets every accessibility call this process makes to time out after the given seconds, starts listening for sleep, wake and app activations, and handles clicks on its notifications.
    public init(callTimeout: TimeInterval) {
        LiveAccessibilityElement.setProcessCallTimeout(callTimeout)
    }

    public func uptime() -> TimeInterval { ProcessInfo.processInfo.systemUptime }
    public func now() -> Date { Date() }
    public func sleep(_ seconds: TimeInterval) { Thread.sleep(forTimeInterval: seconds) }
    public func samplePresence() -> Presence { presence.sample() }
    public func onSleepChange(_ handler: @escaping @Sendable (SleepChange, Date) -> Void) { presence.onSleepChange(handler) }
    public func accessibilityTrusted() -> Bool { isAccessibilityTrusted(prompt: false) }
    public func focusedApplication() -> FocusedApplication? { CaptureAgent.focusedApplication(orFrontmost: frontmost.application) }
    public func frontmostApplication() -> FocusedApplication? { frontmost.application() }

    public func applicationElement(_ processIdentifier: pid_t) -> LiveAccessibilityElement {
        LiveAccessibilityElement.application(processIdentifier)
    }

    public func hasElectronFramework(_ bundle: URL) -> Bool { bundleHasElectronFramework(bundle) }

    public func focusedWindowImage(_ window: FocusedWindow, longEdge: Int) -> WindowImage {
        screenshots.run(timeout: 2, otherwise: .failed) { captureFocusedWindow(window, longEdge: longEdge, answer: $0) }
    }

    public func post(_ notification: UserNotification, shownLater: @escaping @Sendable () -> Void) -> NotificationPosting {
        notifications.post(notification, timeout: 2, shownLater: shownLater)
    }
}
