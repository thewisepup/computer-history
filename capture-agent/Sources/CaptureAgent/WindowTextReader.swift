import Foundation

/// The limits a window read keeps to, and the apps that never get the accessibility flag.
public struct WindowTextSettings: Equatable, Sendable {
    public var textCapBytes: Int
    public var callTimeout: TimeInterval
    public var windowTimeout: TimeInterval
    public var flagOffList: Set<String>

    public init(
        textCapBytes: Int = 50_000,
        callTimeout: TimeInterval = 0.25,
        windowTimeout: TimeInterval = 2,
        flagOffList: Set<String> = []
    ) {
        self.textCapBytes = textCapBytes
        self.callTimeout = callTimeout
        self.windowTimeout = windowTimeout
        self.flagOffList = flagOffList
    }
}

/// What one read of the focused window found: the title, the kept text, the full length in UTF-8 bytes, and whether the read timed out.
public struct WindowText: Equatable, Sendable {
    public let title: String?
    public let text: String
    public let fullLength: Int
    public let timedOut: Bool
}

/// Reads the focused window's title and content text from an application's accessibility tree.
public final class WindowTextReader<Element: AccessibilityElement> {
    let settings: WindowTextSettings
    let applicationElement: (pid_t) -> Element
    let hasElectronFramework: (URL) -> Bool
    let now: () -> TimeInterval
    private var flagChecked: Set<ProcessLaunch> = []

    public init(
        settings: WindowTextSettings,
        applicationElement: @escaping (pid_t) -> Element,
        hasElectronFramework: @escaping (URL) -> Bool,
        now: @escaping () -> TimeInterval
    ) {
        self.settings = settings
        self.applicationElement = applicationElement
        self.hasElectronFramework = hasElectronFramework
        self.now = now
    }

    /// Reads the application's focused window, stopping early with the text so far if a call or the window budget times out.
    public func read(_ application: FocusedApplication) -> WindowText {
        var walk = WindowWalk<Element>(
            capBytes: settings.textCapBytes,
            deadline: now() + settings.windowTimeout,
            now: now
        )
        let app = applicationElement(application.processIdentifier)
        let launch = ProcessLaunch(application)
        if !flagChecked.contains(launch) {
            let needsFlag = needsAccessibilityFlag(application, offList: settings.flagOffList, hasElectronFramework: hasElectronFramework)
            if !needsFlag || setAccessibilityFlags(on: app) {
                flagChecked.insert(launch)
            }
        }
        var title: String?
        if let window = walk.call({ app.element("AXFocusedWindow") }) {
            title = walk.call { window.string("AXTitle") }
            walk.visit(window)
        }
        return WindowText(
            title: title,
            text: walk.text.text,
            fullLength: walk.text.fullLength,
            timedOut: walk.timedOut
        )
    }

    private func setAccessibilityFlags(on app: Element) -> Bool {
        for flag in accessibilityFlags {
            if case .timedOut = app.setTrue(flag) { return false }
        }
        return true
    }
}

/// One launch of an app, so a process id reused by another app or a relaunch is not taken for the old process.
private struct ProcessLaunch: Hashable {
    let processIdentifier: pid_t
    let bundleURL: URL?
    let launchDate: Date?

    init(_ application: FocusedApplication) {
        processIdentifier = application.processIdentifier
        bundleURL = application.bundleURL
        launchDate = application.launchDate
    }
}
