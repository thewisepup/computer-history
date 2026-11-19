import AppKit

/// The application that has keyboard focus.
public struct FocusedApplication: Equatable, Sendable {
    public let processIdentifier: pid_t
    public let bundleIdentifier: String?
    public let bundleURL: URL?
    public let name: String?
    public let launchDate: Date?

    public init(processIdentifier: pid_t, bundleIdentifier: String?, bundleURL: URL?, name: String?, launchDate: Date? = nil) {
        self.processIdentifier = processIdentifier
        self.bundleIdentifier = bundleIdentifier
        self.bundleURL = bundleURL
        self.name = name
        self.launchDate = launchDate
    }
}

/// Follows which app macOS shows in front by listening for app activations.
public final class LiveFrontmostApplication: @unchecked Sendable {
    private let lock = NSLock()
    private var processIdentifier: pid_t?
    private var observer: (any NSObjectProtocol)?

    /// Starts listening for app activations, which arrive on the main run loop.
    public init() {
        processIdentifier = NSWorkspace.shared.frontmostApplication?.processIdentifier
        observer = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: nil
        ) { [weak self] notification in
            let activated = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            self?.set(activated?.processIdentifier)
        }
    }

    deinit {
        observer.map(NSWorkspace.shared.notificationCenter.removeObserver)
    }

    /// Returns the app macOS shows in front.
    public func application() -> FocusedApplication? {
        lock.withLock { processIdentifier }.flatMap(describeApplication)
    }

    private func set(_ value: pid_t?) {
        lock.withLock { processIdentifier = value }
    }
}

/// Asks the system-wide accessibility element for the focused application, falling back to the given app in front.
public func focusedApplication(orFrontmost frontmost: () -> FocusedApplication?) -> FocusedApplication? {
    focusedApplication(
        accessibilityPid: {
            guard case .value(let app) = LiveAccessibilityElement.systemWide.element("AXFocusedApplication") else {
                return nil
            }
            return app.processIdentifier
        },
        workspacePid: { frontmost()?.processIdentifier },
        describe: describeApplication
    )
}

private func describeApplication(_ pid: pid_t) -> FocusedApplication? {
    NSRunningApplication(processIdentifier: pid).map {
        FocusedApplication(
            processIdentifier: pid,
            bundleIdentifier: $0.bundleIdentifier,
            bundleURL: $0.bundleURL,
            name: $0.localizedName,
            launchDate: $0.launchDate
        )
    }
}

func focusedApplication(
    accessibilityPid: () -> pid_t?,
    workspacePid: () -> pid_t?,
    describe: (pid_t) -> FocusedApplication?
) -> FocusedApplication? {
    if let pid = accessibilityPid(), let app = describe(pid) {
        return app
    }
    return workspacePid().flatMap(describe)
}
