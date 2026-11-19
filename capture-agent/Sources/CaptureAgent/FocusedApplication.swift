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

/// Asks the system-wide accessibility element for the focused application, falling back to NSWorkspace.
public func focusedApplication() -> FocusedApplication? {
    focusedApplication(
        accessibilityPid: {
            guard case .value(let app) = LiveAccessibilityElement.systemWide.element("AXFocusedApplication") else {
                return nil
            }
            return app.processIdentifier
        },
        workspacePid: { NSWorkspace.shared.frontmostApplication?.processIdentifier },
        describe: { pid in
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
    )
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
