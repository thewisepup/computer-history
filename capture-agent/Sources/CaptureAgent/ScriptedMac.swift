import Foundation

/// A pretend Mac on a virtual clock, whose focused app, presence and accessibility trees are set by a script or a test.
final class ScriptedMac: Mac, @unchecked Sendable {
    let start: Date
    var clock: TimeInterval = 0
    var callCost: TimeInterval = 0.001
    var callTimeout: TimeInterval = 0.25
    var presence = Presence(idleSeconds: 0, locked: false, asleep: false)
    var trusted = true
    var focused: FocusedApplication?
    var apps: [pid_t: ScriptedElement] = [:]
    var calls: [String] = []

    init(start: Date = Date(timeIntervalSince1970: 0)) {
        self.start = start
    }

    func uptime() -> TimeInterval { clock }
    func now() -> Date { start.addingTimeInterval(clock) }
    func sleep(_ seconds: TimeInterval) { clock += seconds }
    func samplePresence() -> Presence { presence }
    func accessibilityTrusted() -> Bool { trusted }
    func focusedApplication() -> FocusedApplication? { focused }

    func applicationElement(_ processIdentifier: pid_t) -> ScriptedElement {
        guard let app = apps[processIdentifier] else { preconditionFailure("no scripted app has pid \(processIdentifier)") }
        return app
    }

    func fileExists(_ path: String) -> Bool { false }

    func node(_ name: String, role: String, _ attributes: [String: String] = [:], children: [ScriptedElement] = []) -> ScriptedElement {
        ScriptedElement(mac: self, name: name, attributes: attributes.merging(["AXRole": role]) { $1 }, children: children)
    }
}

/// One element of a scripted accessibility tree, where every call costs virtual time and a call for an attribute it hangs on times out.
final class ScriptedElement: AccessibilityElement {
    let mac: ScriptedMac
    let name: String
    var attributes: [String: String]
    var children: [ScriptedElement]
    var focusedWindow: ScriptedElement?
    var hangs: Set<String> = []
    var flagsSet: [String] = []

    init(mac: ScriptedMac, name: String, attributes: [String: String], children: [ScriptedElement]) {
        self.mac = mac
        self.name = name
        self.attributes = attributes
        self.children = children
    }

    func string(_ attribute: String) -> AccessibilityResult<String> {
        perform(attribute) { attributes[attribute].map { .value($0) } ?? .missing }
    }

    func element(_ attribute: String) -> AccessibilityResult<ScriptedElement> {
        perform(attribute) { attribute == "AXFocusedWindow" ? focusedWindow.map { .value($0) } ?? .missing : .missing }
    }

    func elements(_ attribute: String) -> AccessibilityResult<[ScriptedElement]> {
        perform(attribute) { .value(children) }
    }

    func setTrue(_ attribute: String) -> AccessibilityResult<Void> {
        perform(attribute) {
            flagsSet.append(attribute)
            return .value(())
        }
    }

    private func perform<Value>(_ attribute: String, _ body: () -> AccessibilityResult<Value>) -> AccessibilityResult<Value> {
        mac.calls.append("\(name).\(attribute)")
        if hangs.contains(attribute) {
            mac.clock += mac.callTimeout
            return .timedOut
        }
        mac.clock += mac.callCost
        return body()
    }

    static func == (lhs: ScriptedElement, rhs: ScriptedElement) -> Bool { lhs === rhs }
    func hash(into hasher: inout Hasher) { hasher.combine(ObjectIdentifier(self)) }
}
