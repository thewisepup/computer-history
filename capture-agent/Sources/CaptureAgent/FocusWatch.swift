import Foundation

/// Notices when the focused app, its focused window or that window's title changes, by polling accessibility.
struct FocusWatch<Element: AccessibilityElement> {
    let focusedApplication: () -> FocusedApplication?
    let applicationElement: (pid_t) -> Element
    private(set) var application: FocusedApplication?
    private var lastApplication: FocusedApplication?
    private var window: Known<Element?> = .unknown
    private var title: Known<String?> = .unknown

    init(focusedApplication: @escaping () -> FocusedApplication?, applicationElement: @escaping (pid_t) -> Element) {
        self.focusedApplication = focusedApplication
        self.applicationElement = applicationElement
    }

    /// Reads the current focus and returns what changed since the last poll, or nil on the first poll or no change.
    mutating func poll() -> SpoolRecord.Trigger? {
        application = focusedApplication()
        guard let current = application else { return nil }
        let previous = lastApplication
        let sameApp = previous?.processIdentifier == current.processIdentifier
        var nextWindow = sameApp ? window : .unknown
        var nextTitle = sameApp ? title : .unknown
        switch applicationElement(current.processIdentifier).element("AXFocusedWindow") {
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
        let change: SpoolRecord.Trigger? =
            if previous == nil { nil }
            else if !sameApp { .app }
            else if window != nextWindow, nextWindow != .unknown { .window }
            else if title.differs(from: nextTitle) { .title }
            else { nil }
        lastApplication = current
        window = nextWindow
        title = nextTitle
        return change
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
