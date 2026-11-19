import Foundation
@testable import CaptureAgent

final class FakeAccessibilityTree {
    var now: TimeInterval = 0
    var callCost: TimeInterval = 0.001
    var callTimeout: TimeInterval = 0.25
    var calls: [String] = []

    func node(
        _ name: String,
        role: String,
        _ attributes: [String: String] = [:],
        children: [FakeElement] = []
    ) -> FakeElement {
        FakeElement(tree: self, name: name, attributes: attributes.merging(["AXRole": role]) { $1 }, children: children)
    }

    func text(_ value: String) -> FakeElement {
        node(value, role: "AXStaticText", ["AXValue": value])
    }

    func window(_ title: String, children: [FakeElement]) -> FakeElement {
        node("window", role: "AXWindow", ["AXTitle": title], children: children)
    }

    func app(window: FakeElement?) -> FakeElement {
        let app = node("app", role: "AXApplication")
        app.focusedWindow = window
        return app
    }

    func reader(
        _ apps: [pid_t: FakeElement],
        settings: WindowTextSettings = WindowTextSettings(),
        electronBundles: Set<String> = []
    ) -> WindowTextReader<FakeElement> {
        WindowTextReader(
            settings: settings,
            applicationElement: { apps[$0]! },
            fileExists: { path in electronBundles.contains { path.hasPrefix($0) } },
            now: { self.now }
        )
    }

    func reads(of name: String) -> [String] {
        calls.filter { $0.hasPrefix(name + ".") }
    }
}

final class FakeElement: AccessibilityElement {
    let tree: FakeAccessibilityTree
    let name: String
    var attributes: [String: String]
    var children: [FakeElement]
    var focusedWindow: FakeElement?
    var hangs: Set<String> = []
    var flagsSet: [String] = []

    init(tree: FakeAccessibilityTree, name: String, attributes: [String: String], children: [FakeElement]) {
        self.tree = tree
        self.name = name
        self.attributes = attributes
        self.children = children
    }

    func string(_ attribute: String) -> AccessibilityResult<String> {
        perform(attribute) { attributes[attribute].map { .value($0) } ?? .missing }
    }

    func element(_ attribute: String) -> AccessibilityResult<FakeElement> {
        perform(attribute) { focusedWindow.map { .value($0) } ?? .missing }
    }

    func elements(_ attribute: String) -> AccessibilityResult<[FakeElement]> {
        perform(attribute) { .value(children) }
    }

    func setTrue(_ attribute: String) -> AccessibilityResult<Void> {
        perform(attribute) {
            flagsSet.append(attribute)
            return .value(())
        }
    }

    private func perform<Value>(_ attribute: String, _ body: () -> AccessibilityResult<Value>) -> AccessibilityResult<Value> {
        tree.calls.append("\(name).\(attribute)")
        if hangs.contains(attribute) {
            tree.now += tree.callTimeout
            return .timedOut
        }
        tree.now += tree.callCost
        return body()
    }
}
