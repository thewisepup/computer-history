import ApplicationServices

/// The outcome of one accessibility call.
public enum AccessibilityResult<Value> {
    case value(Value)
    case missing
    case timedOut
}

/// One element of an application's accessibility tree, read one attribute at a time.
public protocol AccessibilityElement {
    func string(_ attribute: String) -> AccessibilityResult<String>
    func element(_ attribute: String) -> AccessibilityResult<Self>
    func elements(_ attribute: String) -> AccessibilityResult<[Self]>
    func setTrue(_ attribute: String) -> AccessibilityResult<Void>
}

/// An accessibility element of a running application, read through the macOS Accessibility API.
public struct LiveAccessibilityElement: AccessibilityElement {
    let raw: AXUIElement

    /// Sets how long every accessibility call this process makes waits for an answer.
    public static func setProcessCallTimeout(_ timeout: TimeInterval) {
        AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), Float(timeout))
    }

    /// The element for a running application.
    public static func application(_ processIdentifier: pid_t) -> Self {
        Self(raw: AXUIElementCreateApplication(processIdentifier))
    }

    /// The system-wide element.
    public static var systemWide: Self {
        Self(raw: AXUIElementCreateSystemWide())
    }

    public var processIdentifier: pid_t? {
        var pid: pid_t = 0
        return AXUIElementGetPid(raw, &pid) == .success ? pid : nil
    }

    public func string(_ attribute: String) -> AccessibilityResult<String> {
        switch copy(attribute) {
        case .value(let value): (value as? String).map { .value($0) } ?? .missing
        case .missing: .missing
        case .timedOut: .timedOut
        }
    }

    public func element(_ attribute: String) -> AccessibilityResult<Self> {
        switch copy(attribute) {
        case .value(let value) where CFGetTypeID(value) == AXUIElementGetTypeID():
            .value(Self(raw: value as! AXUIElement))
        case .value, .missing: .missing
        case .timedOut: .timedOut
        }
    }

    public func elements(_ attribute: String) -> AccessibilityResult<[Self]> {
        switch copy(attribute) {
        case .value(let value): (value as? [AXUIElement]).map { .value($0.map(Self.init)) } ?? .missing
        case .missing: .missing
        case .timedOut: .timedOut
        }
    }

    public func setTrue(_ attribute: String) -> AccessibilityResult<Void> {
        switch AXUIElementSetAttributeValue(raw, attribute as CFString, kCFBooleanTrue) {
        case .success: .value(())
        case .cannotComplete: .timedOut
        default: .missing
        }
    }

    private func copy(_ attribute: String) -> AccessibilityResult<CFTypeRef> {
        var value: CFTypeRef?
        switch AXUIElementCopyAttributeValue(raw, attribute as CFString, &value) {
        case .success: return value.map { .value($0) } ?? .missing
        case .cannotComplete: return .timedOut
        default: return .missing
        }
    }
}
