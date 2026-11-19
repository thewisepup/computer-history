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
    let mac = ScriptedMac()
    var focused: FocusedApplication? = plainApp
    var apps: [pid_t: ScriptedElement] = [:]
    lazy var notes = mac.window("Notes", children: [mac.text("hello")])
    lazy var tab = mac.window("Inbox", children: [mac.text("mail")])
    lazy var vault = mac.node("vault", role: "AXWindow", ["AXTitle": "Vault"], children: [mac.text("secret")])

    init() {
        apps[plainApp.processIdentifier] = mac.app(window: notes)
        apps[chrome.processIdentifier] = mac.app(window: tab)
        let passwords = mac.node("passwords", role: "AXApplication")
        passwords.focusedWindow = vault
        apps[onePassword.processIdentifier] = passwords
    }

    var appWatch: AppWatch {
        AppWatch(focusedApplication: { self.focused })
    }

    var windowWatch: WindowWatch<ScriptedElement> {
        WindowWatch(applicationElement: { self.apps[$0]! })
    }

    func passwordAppCalls() -> [String] {
        mac.calls.filter { $0.hasPrefix("passwords.") || $0.hasPrefix("vault.") || $0.hasPrefix("secret.") }
    }
}
