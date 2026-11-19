import Foundation

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

    mutating func poll() -> FocusChange? {
        application = applicationToJudge()
        guard let current = application else { return nil }
        defer { lastApplication = current }
        guard let previous = lastApplication else { return nil }
        return previous.processIdentifier == current.processIdentifier ? nil : .app
    }

    private func applicationToJudge() -> FocusedApplication? {
        if let frontmost = frontmostApplication(), denylist.contains(frontmost) { return frontmost }
        return focusedApplication()
    }
}

struct WindowWatch<Element: AccessibilityElement> {
    let applicationElement: (pid_t) -> Element
    private var processIdentifier: pid_t?
    private var window: Known<Element?> = .unknown
    private var title: Known<String?> = .unknown

    init(applicationElement: @escaping (pid_t) -> Element) {
        self.applicationElement = applicationElement
    }

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
