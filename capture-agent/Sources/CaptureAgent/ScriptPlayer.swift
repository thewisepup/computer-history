import Foundation

/// A script that cannot be played: an unknown app or window, a bad app id, steps out of order, or no end.
struct ScriptError: Error, Equatable, CustomStringConvertible {
    let description: String
}

/// Plays a capture script on a scripted Mac, changing what it shows as each step comes due.
struct ScriptPlayer {
    enum Ending: Equatable {
        case end, crash
    }

    private struct App {
        let application: FocusedApplication
        let element: ScriptedElement
        let windows: [String: ScriptedElement]
    }

    let mac: ScriptedMac
    let pause: PauseSwitch
    private let apps: [String: App]
    private var pending: [CaptureScript.Step]
    private(set) var ending: Ending?

    init(_ script: CaptureScript, mac: ScriptedMac, pause: PauseSwitch) throws {
        self.mac = mac
        self.pause = pause
        var apps: [String: App] = [:]
        for (index, id) in script.apps.keys.sorted().enumerated() {
            guard id.wholeMatch(of: /[A-Za-z0-9_-]+/) != nil else {
                throw ScriptError(description: "app id \(id) may hold only letters, digits, - and _")
            }
            let spec = script.apps[id]!
            let application = FocusedApplication(
                processIdentifier: pid_t(100 + index), bundleIdentifier: spec.bundleID, bundleURL: nil, name: spec.name
            )
            let element = mac.node(id, role: "AXApplication")
            var windows: [String: ScriptedElement] = [:]
            for (windowID, node) in spec.windows {
                windows[windowID] = Self.build(node, name: "\(id)/\(windowID)", on: mac)
            }
            if let focused = spec.focusedWindow {
                guard let window = windows[focused] else { throw ScriptError(description: "app \(id) has no window \(focused)") }
                element.focusedWindow = window
            }
            mac.apps[application.processIdentifier] = element
            apps[id] = App(application: application, element: element, windows: windows)
        }
        self.apps = apps
        pending = script.steps
        guard zip(pending, pending.dropFirst()).allSatisfy({ $0.at <= $1.at }) else {
            throw ScriptError(description: "steps must be in time order")
        }
        guard let last = pending.last, last.action == .end || last.action == .crash else {
            throw ScriptError(description: "the last step must be end or crash")
        }
        for step in pending { try check(step.action) }
    }

    /// Applies every step due by the given time, and returns false once the script has ended.
    mutating func play(upTo time: TimeInterval) throws -> Bool {
        while ending == nil, let step = pending.first, step.at <= time {
            pending.removeFirst()
            try apply(step.action)
        }
        return ending == nil
    }

    /// How many accessibility calls each app's elements received, by app id.
    var callCounts: [String: Int] {
        apps.keys.reduce(into: [:]) { counts, id in
            counts[id] = mac.calls.count { $0.hasPrefix(id + ".") || $0.hasPrefix(id + "/") }
        }
    }

    private mutating func apply(_ action: CaptureScript.Action) throws {
        switch action {
        case .focus(let id):
            mac.focused = apps[id]!.application
        case .focusWindow(let ref):
            apps[ref.app]!.element.focusedWindow = apps[ref.app]!.windows[ref.window]!
        case .setTitle(let change):
            apps[change.app]!.windows[change.window]!.attributes["AXTitle"] = change.title
        case .presence(let presence):
            mac.presence = presence
        case .pause:
            try pause.pause()
        case .resume:
            try pause.resume()
        case .end:
            ending = .end
        case .crash:
            ending = .crash
        }
    }

    private func check(_ action: CaptureScript.Action) throws {
        switch action {
        case .focus(let id):
            guard apps[id] != nil else { throw ScriptError(description: "no app \(id)") }
        case .focusWindow(let ref):
            guard apps[ref.app]?.windows[ref.window] != nil else { throw ScriptError(description: "no window \(ref.app)/\(ref.window)") }
        case .setTitle(let change):
            guard apps[change.app]?.windows[change.window] != nil else {
                throw ScriptError(description: "no window \(change.app)/\(change.window)")
            }
        case .presence, .pause, .resume, .end, .crash:
            return
        }
    }

    private static func build(_ node: CaptureScript.Node, name: String, on mac: ScriptedMac) -> ScriptedElement {
        let element = mac.node(name, role: node.role, node.attributes, children: node.children.map { build($0, name: name, on: mac) })
        element.hangs = Set(node.hangs)
        return element
    }
}
