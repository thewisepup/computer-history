/// What the focused element of an application is, for deciding whether a screenshot may be taken.
enum FocusedField: Equatable {
    case password, other, unknown
}

/// Asks the application's accessibility tree whether its focused element is a password field, by role or subrole; no answer is unknown.
func focusedField<Element: AccessibilityElement>(in application: Element) -> FocusedField {
    let secure = "AXSecureTextField"
    switch application.element("AXFocusedUIElement") {
    case .missing:
        return .other
    case .timedOut:
        return .unknown
    case .value(let focused):
        guard case .value(let role) = focused.string("AXRole") else { return .unknown }
        switch focused.string("AXSubrole") {
        case .timedOut: return .unknown
        case .value(secure): return .password
        case .value, .missing: return role == secure ? .password : .other
        }
    }
}
