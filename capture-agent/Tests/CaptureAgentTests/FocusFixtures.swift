import Foundation
@testable import CaptureAgent

let present = Presence(idleSeconds: 0, locked: false, asleep: false)

final class FocusFixture {
    let tree = FakeAccessibilityTree()
    var focused: FocusedApplication? = plainApp
    var apps: [pid_t: FakeElement] = [:]
    lazy var notes = tree.window("Notes", children: [tree.text("hello")])
    lazy var tab = tree.window("Inbox", children: [tree.text("mail")])

    init() {
        apps[plainApp.processIdentifier] = tree.app(window: notes)
        apps[chrome.processIdentifier] = tree.app(window: tab)
    }

    func watch() -> FocusWatch<FakeElement> {
        FocusWatch(focusedApplication: { self.focused }, applicationElement: { self.apps[$0]! })
    }
}
