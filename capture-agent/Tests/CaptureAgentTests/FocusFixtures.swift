import Foundation
@testable import CaptureAgent

let present = Presence(idleSeconds: 0, locked: false, asleep: false)

let plainApp = FocusedApplication(
    processIdentifier: 100,
    bundleIdentifier: "com.apple.TextEdit",
    bundleURL: URL(filePath: "/System/Applications/TextEdit.app"),
    name: "TextEdit"
)

let chrome = FocusedApplication(
    processIdentifier: 200,
    bundleIdentifier: "com.google.Chrome",
    bundleURL: URL(filePath: "/Applications/Google Chrome.app"),
    name: "Google Chrome"
)

let cursor = FocusedApplication(
    processIdentifier: 300,
    bundleIdentifier: "com.todesktop.230313mzl4w4u92",
    bundleURL: URL(filePath: "/Applications/Cursor.app"),
    name: "Cursor"
)

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
        AppWatch(
            focusedApplication: mac.focusedApplication,
            frontmostApplication: mac.frontmostApplication,
            denylist: Denylist()
        )
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
        electronBundles: Set<String> = [],
        denylist: Denylist = Denylist()
    ) -> WindowTextReader<ScriptedElement> {
        WindowTextReader(
            settings: settings,
            denylist: denylist,
            applicationElement: { apps[$0]! },
            hasElectronFramework: { electronBundles.contains($0.path) },
            now: { self.clock }
        )
    }

    func reads(of name: String) -> [String] {
        calls.filter { $0.hasPrefix(name + ".") }
    }
}
