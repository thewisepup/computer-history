import CoreGraphics
import Foundation

struct ScriptError: Error, Equatable, CustomStringConvertible {
    let description: String
}

struct ScriptPlayer {
    enum Ending: Equatable {
        case end, crash
    }

    private struct App {
        let application: FocusedApplication
        let element: ScriptedElement
        let windows: [String: ScriptedElement]
        let elements: [String: [String: ScriptedElement]]
    }

    let mac: ScriptedMac
    let pause: PauseSwitch
    let recognizedTexts: [CGWindowID: String]
    private let apps: [String: App]
    private let picture: (FocusedWindow, Int) -> WindowImage
    private var pending: [CaptureScript.Step]
    private(set) var ending: Ending?

    init(_ script: CaptureScript, mac: ScriptedMac, pause: PauseSwitch) throws {
        self.mac = mac
        self.pause = pause
        var apps: [String: App] = [:]
        var recognizedTexts: [CGWindowID: String] = [:]
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
            var elements: [String: [String: ScriptedElement]] = [:]
            for (windowID, node) in spec.windows {
                var ids: [String: ScriptedElement] = [:]
                let window = try Self.build(node, name: "\(id)/\(windowID)", on: mac, ids: &ids)
                windows[windowID] = window
                elements[windowID] = ids
                recognizedTexts[window.windowID] = node.recognizedText
            }
            if let focused = spec.focusedWindow {
                guard let window = windows[focused] else { throw ScriptError(description: "app \(id) has no window \(focused)") }
                element.focusedWindow = window
            }
            mac.apps[application.processIdentifier] = element
            apps[id] = App(application: application, element: element, windows: windows, elements: elements)
        }
        self.apps = apps
        self.recognizedTexts = recognizedTexts
        picture = mac.windowImage
        pending = script.steps
        guard zip(pending, pending.dropFirst()).allSatisfy({ $0.at <= $1.at }) else {
            throw ScriptError(description: "steps must be in time order")
        }
        guard let last = pending.last, last.action == .end || last.action == .crash else {
            throw ScriptError(description: "the last step must be end or crash")
        }
        for step in pending { try check(step.action) }
    }

    mutating func play(upTo time: TimeInterval) throws -> Bool {
        while ending == nil, let step = pending.first, step.at <= time {
            pending.removeFirst()
            try apply(step.action)
        }
        return ending == nil
    }

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
        case .focusElement(let ref):
            let app = apps[ref.app]!
            app.element.focusedElement = ref.window.flatMap { window in ref.element.flatMap { app.elements[window]![$0] } }
        case .windowImage(let answer):
            mac.windowImage = switch answer {
            case .picture: picture
            case .noPermission: { _, _ in .noPermission }
            case .failed: { _, _ in .failed }
            }
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
        case .focusElement(let ref):
            guard let app = apps[ref.app] else { throw ScriptError(description: "no app \(ref.app)") }
            switch (ref.window, ref.element) {
            case (nil, nil):
                return
            case (let window?, let element?):
                guard let ids = app.elements[window] else { throw ScriptError(description: "no window \(ref.app)/\(window)") }
                guard ids[element] != nil else { throw ScriptError(description: "no element \(element) in \(ref.app)/\(window)") }
            default:
                throw ScriptError(description: "focus_element needs both window and element, or neither")
            }
        case .windowImage, .presence, .pause, .resume, .end, .crash:
            return
        }
    }

    private static func build(
        _ node: CaptureScript.Node, name: String, on mac: ScriptedMac, ids: inout [String: ScriptedElement]
    ) throws -> ScriptedElement {
        let children = try node.children.map { try build($0, name: name, on: mac, ids: &ids) }
        let element = mac.node(name, role: node.role, node.attributes, children: children)
        element.hangs = Set(node.hangs)
        if let id = node.id {
            guard ids[id] == nil else { throw ScriptError(description: "\(name) has two elements with id \(id)") }
            ids[id] = element
        }
        return element
    }
}

/// Saves pictures through another store and reads back, for each saved file, the scripted recognized text of the window focused when it was saved.
final class ScriptedRecognition: ImageStore, @unchecked Sendable {
    private let images: any ImageStore
    private let mac: ScriptedMac
    private let texts: [CGWindowID: String]
    private let lock = NSLock()
    private var saved: [URL: String] = [:]

    init(images: any ImageStore, mac: ScriptedMac, texts: [CGWindowID: String]) {
        self.images = images
        self.mac = mac
        self.texts = texts
    }

    func save(_ image: CGImage, id: UUID, at date: Date) throws -> SavedImage {
        let file = try images.save(image, id: id, at: date)
        let window = mac.focused.flatMap { mac.apps[$0.processIdentifier]?.focusedWindow }
        let text = window.flatMap { texts[$0.windowID] } ?? ""
        lock.withLock { saved[file.file] = text }
        return file
    }

    func recognizedText(inImageAt file: URL) -> String {
        lock.withLock { saved[file] ?? "" }
    }
}
