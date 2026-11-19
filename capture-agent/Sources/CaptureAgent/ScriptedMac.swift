import Foundation

final class ScriptedMac {
    var clock: TimeInterval = 0
    var callCost: TimeInterval = 0.001
    var callTimeout: TimeInterval = 0.25
    var calls: [String] = []

    func node(
        _ name: String,
        role: String,
        _ attributes: [String: String] = [:],
        children: [ScriptedElement] = []
    ) -> ScriptedElement {
        ScriptedElement(mac: self, name: name, attributes: attributes.merging(["AXRole": role]) { $1 }, children: children)
    }

    func text(_ value: String) -> ScriptedElement {
        node(value, role: "AXStaticText", ["AXValue": value])
    }

    func window(_ title: String, children: [ScriptedElement]) -> ScriptedElement {
        node("window", role: "AXWindow", ["AXTitle": title], children: children)
    }

    func app(window: ScriptedElement?) -> ScriptedElement {
        let app = node("app", role: "AXApplication")
        app.focusedWindow = window
        return app
    }

    func reader(
        _ apps: [pid_t: ScriptedElement],
        settings: WindowTextSettings = WindowTextSettings(),
        electronBundles: Set<String> = []
    ) -> WindowTextReader<ScriptedElement> {
        WindowTextReader(
            settings: settings,
            applicationElement: { apps[$0]! },
            fileExists: { path in electronBundles.contains { path.hasPrefix($0) } },
            now: { self.clock }
        )
    }

    func reads(of name: String) -> [String] {
        calls.filter { $0.hasPrefix(name + ".") }
    }
}

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
        perform(attribute) { focusedWindow.map { .value($0) } ?? .missing }
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
}

extension ScriptedElement: Hashable {
    static func == (lhs: ScriptedElement, rhs: ScriptedElement) -> Bool { lhs === rhs }
    func hash(into hasher: inout Hasher) { hasher.combine(ObjectIdentifier(self)) }
}
