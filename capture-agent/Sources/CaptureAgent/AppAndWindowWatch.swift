import Foundation

/// What changed about the focus: the focused app, its focused window, or that window's title.
enum FocusChange: Equatable {
    case app, window, title

    var trigger: SpoolRecord.Trigger {
        switch self {
        case .app: .app
        case .window: .window
        case .title: .title
        }
    }
}

/// Notices when the app to judge changes, asking only which apps are focused and frontmost and never touching their windows.
struct AppWatch {
    let focusedApplication: () -> FocusedApplication?
    let frontmostApplication: () -> FocusedApplication?
    let denylist: Denylist
    private(set) var application: FocusedApplication?
    private var lastApplication: FocusedApplication?

    init(
        focusedApplication: @escaping () -> FocusedApplication?,
        frontmostApplication: @escaping () -> FocusedApplication?,
        denylist: Denylist
    ) {
        self.focusedApplication = focusedApplication
        self.frontmostApplication = frontmostApplication
        self.denylist = denylist
    }

    /// Reads the focused app, or the frontmost one when that is denylisted, and returns `app` if it differs from the last known one, or nil on the first poll, no change or no app.
    mutating func poll() -> FocusChange? {
        application = frontmostApplication().flatMap { denylist.contains($0) ? $0 : nil } ?? focusedApplication()
        guard let current = application else { return nil }
        defer { lastApplication = current }
        guard let previous = lastApplication else { return nil }
        return previous.processIdentifier == current.processIdentifier ? nil : .app
    }
}

/// Notices when an app's focused window or that window's title changes, by polling accessibility.
struct WindowWatch<Element: AccessibilityElement> {
    let applicationElement: (pid_t) -> Element
    private var processIdentifier: pid_t?
    private var window: Known<Element?> = .unknown
    private var title: Known<String?> = .unknown

    init(applicationElement: @escaping (pid_t) -> Element) {
        self.applicationElement = applicationElement
    }

    /// Reads the app's focused window and title and returns what changed, or nil on the first poll of a newly focused app or no change.
    mutating func poll(_ application: FocusedApplication) -> FocusChange? {
        let sameApp = processIdentifier == application.processIdentifier
        if !sameApp { forget() }
        var nextWindow = window
        var nextTitle = title
        switch applicationElement(application.processIdentifier).element("AXFocusedWindow") {
        case .value(let focused):
            if nextWindow != .known(focused) { nextTitle = .unknown }
            nextWindow = .known(focused)
            switch focused.string("AXTitle") {
            case .value(let value): nextTitle = .known(value)
            case .missing: nextTitle = .known(nil)
            case .timedOut: break
            }
        case .missing:
            nextWindow = .known(nil)
            nextTitle = .known(nil)
        case .timedOut:
            break
        }
        let change: FocusChange? =
            if !sameApp { nil }
            else if window != nextWindow, nextWindow != .unknown { .window }
            else if title.differs(from: nextTitle) { .title }
            else { nil }
        processIdentifier = application.processIdentifier
        window = nextWindow
        title = nextTitle
        return change
    }

    /// Drops what is known about the last app's window.
    mutating func forget() {
        processIdentifier = nil
        window = .unknown
        title = .unknown
    }
}

private enum Known<Value: Equatable>: Equatable {
    case unknown
    case known(Value)

    func differs(from other: Known) -> Bool {
        guard case .known(let mine) = self, case .known(let theirs) = other else { return false }
        return mine != theirs
    }
}
