import Foundation
@testable import CaptureAgent

let present = Presence(idleSeconds: 0, locked: false, asleep: false)

let onePassword = FocusedApplication(
    processIdentifier: 400,
    bundleIdentifier: "com.1password.1password",
    bundleURL: URL(filePath: "/Applications/1Password.app"),
    name: "1Password"
)

final class FocusFixture {
    let tree = FakeAccessibilityTree()
    var focused: FocusedApplication? = plainApp
    var apps: [pid_t: FakeElement] = [:]
    lazy var notes = tree.window("Notes", children: [tree.text("hello")])
    lazy var tab = tree.window("Inbox", children: [tree.text("mail")])
    lazy var vault = tree.node("vault", role: "AXWindow", ["AXTitle": "Vault"], children: [tree.text("secret")])

    init() {
        apps[plainApp.processIdentifier] = tree.app(window: notes)
        apps[chrome.processIdentifier] = tree.app(window: tab)
        let passwords = tree.node("passwords", role: "AXApplication")
        passwords.focusedWindow = vault
        apps[onePassword.processIdentifier] = passwords
    }

    var appWatch: AppWatch {
        AppWatch(focusedApplication: { self.focused })
    }

    var windowWatch: WindowWatch<FakeElement> {
        WindowWatch(applicationElement: { self.apps[$0]! })
    }

    func passwordAppCalls() -> [String] {
        tree.calls.filter { $0.hasPrefix("passwords.") || $0.hasPrefix("vault.") || $0.hasPrefix("secret.") }
    }
}
