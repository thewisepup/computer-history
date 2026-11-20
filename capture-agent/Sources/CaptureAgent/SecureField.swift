/// Whether the application's focused element is a password field, by its role or subrole.
func secureTextFieldFocused<Element: AccessibilityElement>(in application: Element) -> Bool {
    guard case .value(let focused) = application.element("AXFocusedUIElement") else { return false }
    return ["AXRole", "AXSubrole"].contains { attribute in
        if case .value("AXSecureTextField") = focused.string(attribute) { return true }
        return false
    }
}
