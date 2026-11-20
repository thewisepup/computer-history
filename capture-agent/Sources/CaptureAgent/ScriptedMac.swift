import CoreGraphics
import Foundation

final class ScriptedMac: Mac, @unchecked Sendable {
    let start: Date
    var clock: TimeInterval = 0
    var callCost: TimeInterval = 0.001
    var callTimeout: TimeInterval = 0.25
    var presence = Presence(idleSeconds: 0, locked: false, asleep: false)
    var trusted = true
    var focused: FocusedApplication?
    var frontmost: FocusedApplication?
    var apps: [pid_t: ScriptedElement] = [:]
    var calls: [String] = []
    var windowImage: (FocusedApplication, String?) -> WindowImage = { _, _ in .image(fixtureImage(width: 1600, height: 1000)) }
    var windowImageRequests: [pid_t] = []

    init(start: Date = Date(timeIntervalSince1970: 0)) {
        self.start = start
    }

    func uptime() -> TimeInterval { clock }
    func now() -> Date { start.addingTimeInterval(clock) }
    func sleep(_ seconds: TimeInterval) { clock += seconds }
    func samplePresence() -> Presence { presence }
    func accessibilityTrusted() -> Bool { trusted }
    func focusedApplication() -> FocusedApplication? { focused }
    func frontmostApplication() -> FocusedApplication? { frontmost ?? focused }

    func applicationElement(_ processIdentifier: pid_t) -> ScriptedElement {
        guard let app = apps[processIdentifier] else { preconditionFailure("no scripted app has pid \(processIdentifier)") }
        return app
    }

    func hasElectronFramework(_ bundle: URL) -> Bool { false }

    func focusedWindowImage(_ application: FocusedApplication, title: String?) -> WindowImage {
        windowImageRequests.append(application.processIdentifier)
        return windowImage(application, title)
    }

    func node(_ name: String, role: String, _ attributes: [String: String] = [:], children: [ScriptedElement] = []) -> ScriptedElement {
        ScriptedElement(mac: self, name: name, attributes: attributes.merging(["AXRole": role]) { $1 }, children: children)
    }
}

final class ScriptedElement: AccessibilityElement {
    let mac: ScriptedMac
    let name: String
    var attributes: [String: String]
    var children: [ScriptedElement]
    var focusedWindow: ScriptedElement?
    var focusedElement: ScriptedElement?
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
        perform(attribute) {
            let focused = switch attribute {
            case "AXFocusedWindow": focusedWindow
            case "AXFocusedUIElement": focusedElement
            default: nil as ScriptedElement?
            }
            return focused.map { .value($0) } ?? .missing
        }
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

/// A striped test image whose stripes shift with the seed, so different seeds give different pictures.
func fixtureImage(width: Int, height: Int, seed: Int = 0) -> CGImage {
    let context = CGContext(
        data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
    )!
    let stripe = max(1, width / 24)
    for (index, x) in stride(from: 0, to: width, by: stripe).enumerated() {
        let shade = CGFloat((index * 7 + seed * 3) % 11) / 10
        context.setFillColor(red: shade, green: 1 - shade, blue: CGFloat((index + seed) % 2), alpha: 1)
        context.fill(CGRect(x: x, y: 0, width: stripe, height: height))
    }
    return context.makeImage()!
}
