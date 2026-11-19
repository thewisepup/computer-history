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
    let mac = ScriptedMac(start: utc("2026-11-18T09:00:00.000Z"))
    lazy var notes = mac.window("Notes", children: [mac.text("hello")])
    lazy var tab = mac.window("Inbox", children: [mac.text("mail")])
    lazy var vault = mac.node("vault", role: "AXWindow", ["AXTitle": "Vault"], children: [mac.text("secret")])

    init() {
        mac.focused = plainApp
        mac.apps[plainApp.processIdentifier] = mac.app(window: notes)
        mac.apps[chrome.processIdentifier] = mac.app(window: tab)
        let passwords = mac.node("passwords", role: "AXApplication")
        passwords.focusedWindow = vault
        mac.apps[onePassword.processIdentifier] = passwords
    }

    var appWatch: AppWatch {
        AppWatch(focusedApplication: mac.focusedApplication)
    }

    var windowWatch: WindowWatch<ScriptedElement> {
        WindowWatch(applicationElement: mac.applicationElement)
    }

    func passwordAppCalls() -> [String] {
        mac.calls.filter { $0.hasPrefix("passwords.") || $0.hasPrefix("vault.") || $0.hasPrefix("secret.") }
    }
}

extension ScriptedMac {
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
