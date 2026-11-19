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

/// What one read of the focused window found, with the full length in UTF-8 bytes.
public struct WindowText: Equatable, Sendable {
    public let title: String?
    public let text: String
    public let fullLength: Int
    public let cutOff: Bool
    public let timedOut: Bool
    public let sha256: String
}

/// Reads the focused window's title and content text from an application's accessibility tree.
public final class WindowTextReader<Element: AccessibilityElement> {
    let settings: WindowTextSettings
    let applicationElement: (pid_t) -> Element
    let fileExists: (String) -> Bool
    let now: () -> TimeInterval
    private var flagChecked: Set<pid_t> = []

    public init(
        settings: WindowTextSettings,
        applicationElement: @escaping (pid_t) -> Element,
        fileExists: @escaping (String) -> Bool,
        now: @escaping () -> TimeInterval
    ) {
        self.settings = settings
        self.applicationElement = applicationElement
        self.fileExists = fileExists
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
        if !flagChecked.contains(application.processIdentifier) {
            let needsFlag = needsAccessibilityFlag(application, offList: settings.flagOffList, fileExists: fileExists)
            if !needsFlag || setAccessibilityFlags(on: app) {
                flagChecked.insert(application.processIdentifier)
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
            cutOff: walk.text.cutOff,
            timedOut: walk.timedOut,
            sha256: walk.text.sha256
        )
    }

    private func setAccessibilityFlags(on app: Element) -> Bool {
        for flag in accessibilityFlags {
            if case .timedOut = app.setTrue(flag) { return false }
        }
        return true
    }
}

extension WindowTextReader where Element == LiveAccessibilityElement {
    /// Creates a reader over the live accessibility API.
    public convenience init(settings: WindowTextSettings) {
        LiveAccessibilityElement.setProcessCallTimeout(settings.callTimeout)
        self.init(
            settings: settings,
            applicationElement: LiveAccessibilityElement.application,
            fileExists: { FileManager.default.fileExists(atPath: $0) },
            now: { ProcessInfo.processInfo.systemUptime }
        )
    }
}
