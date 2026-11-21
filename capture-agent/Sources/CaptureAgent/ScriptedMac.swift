import CoreGraphics
import Foundation

final class ScriptedMac: Mac, @unchecked Sendable {
    let start: Date
    var clock: TimeInterval = 0
    var callCost: TimeInterval = 0.001
    var callTimeout: TimeInterval = 0.25
    var presence = Presence(idleSeconds: 0, locked: false, asleep: false) {
        didSet {
            if presence.asleep != oldValue.asleep { sleepChanged(presence.asleep ? .willSleep : .didWake) }
        }
    }
    var trusted = true
    var focused: FocusedApplication?
    var frontmost: FocusedApplication?
    var apps: [pid_t: ScriptedElement] = [:]
    var calls: [String] = []
    var windowImage: (FocusedWindow, Int) -> WindowImage = { _, _ in .failed }
    var windowImageRequests: [pid_t] = []
    var notificationPosting = NotificationPosting.posted
    var notifications: [UserNotification] = []
    var postedLater: [@Sendable () -> Void] = []
    var onCall: (String) -> Void = { _ in }
    private var sleepHandler: @Sendable (SleepChange, Date) -> Void = { _, _ in }
    private var elements: CGWindowID = 0

    init(start: Date = Date(timeIntervalSince1970: 0)) {
        self.start = start
        windowImage = { [unowned self] window, _ in
            .image(fixtureImage(width: 1600, height: 1000), windowID: apps[window.processIdentifier]?.focusedWindow?.windowID ?? 0)
        }
    }

    func uptime() -> TimeInterval { clock }
    func now() -> Date { start.addingTimeInterval(clock) }
    func sleep(_ seconds: TimeInterval) { clock += seconds }
    func samplePresence() -> Presence { presence }
    func onSleepChange(_ handler: @escaping @Sendable (SleepChange, Date) -> Void) { sleepHandler = handler }

    /// Tells the sleep handler of a sleep or wake now, as changing presence.asleep does.
    func sleepChanged(_ change: SleepChange) { sleepHandler(change, now()) }

    func accessibilityTrusted() -> Bool { trusted }

    func focusedApplication() -> FocusedApplication? {
        onCall("focusedApplication")
        return focused
    }

    func frontmostApplication() -> FocusedApplication? {
        onCall("frontmostApplication")
        return frontmost ?? focused
    }

    func applicationElement(_ processIdentifier: pid_t) -> ScriptedElement {
        guard let app = apps[processIdentifier] else { preconditionFailure("no scripted app has pid \(processIdentifier)") }
        return app
    }

    func hasElectronFramework(_ bundle: URL) -> Bool { false }

    func focusedWindowImage(_ window: FocusedWindow, longEdge: Int) -> WindowImage {
        windowImageRequests.append(window.processIdentifier)
        return windowImage(window, longEdge)
    }

    func post(_ notification: UserNotification, shownLater: @escaping @Sendable () -> Void) -> NotificationPosting {
        notifications.append(notification)
        if notificationPosting == .awaitingPermission { postedLater.append(shownLater) }
        return notificationPosting
    }

    func node(_ name: String, role: String, _ attributes: [String: String] = [:], children: [ScriptedElement] = []) -> ScriptedElement {
        elements += 1
        return ScriptedElement(
            mac: self, name: name, windowID: elements, attributes: attributes.merging(["AXRole": role]) { $1 }, children: children
        )
    }
}

final class ScriptedElement: AccessibilityElement {
    let mac: ScriptedMac
    let name: String
    let windowID: CGWindowID
    var attributes: [String: String]
    var children: [ScriptedElement]
    var focusedWindow: ScriptedElement?
    var focusedElement: ScriptedElement?
    var bounds: CGRect? = CGRect(x: 0, y: 25, width: 1600, height: 1000)
    var hangs: Set<String> = []
    var flagsSet: [String] = []

    init(mac: ScriptedMac, name: String, windowID: CGWindowID, attributes: [String: String], children: [ScriptedElement]) {
        self.mac = mac
        self.name = name
        self.windowID = windowID
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

    func frame() -> AccessibilityResult<CGRect> {
        perform("AXFrame") { bounds.map { .value($0) } ?? .missing }
    }

    private func perform<Value>(_ attribute: String, _ body: () -> AccessibilityResult<Value>) -> AccessibilityResult<Value> {
        mac.calls.append("\(name).\(attribute)")
        mac.onCall("\(name).\(attribute)")
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
