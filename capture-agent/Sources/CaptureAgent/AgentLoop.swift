import Foundation

/// The long-running agent that macOS starts at login.
public struct AgentLoop: Sendable {
    public static let heartbeatInterval: TimeInterval = 60

    let accessibilityTrusted: @Sendable (_ prompt: Bool) -> Bool
    let log: @Sendable (String) -> Void

    public init(
        accessibilityTrusted: @escaping @Sendable (_ prompt: Bool) -> Bool,
        log: @escaping @Sendable (String) -> Void
    ) {
        self.accessibilityTrusted = accessibilityTrusted
        self.log = log
    }

    /// Checks Accessibility once, then logs a heartbeat on the main run loop forever.
    public func run() -> Never {
        start()
        Timer.scheduledTimer(withTimeInterval: Self.heartbeatInterval, repeats: true) { _ in
            heartbeat()
        }
        RunLoop.main.run()
        fatalError("the main run loop returned")
    }

    /// Logs whether Accessibility is granted and asks macOS to prompt for it if not.
    func start() {
        if accessibilityTrusted(true) {
            log("started, accessibility granted")
        } else {
            log("started, accessibility missing, asked macOS to prompt for it")
        }
    }

    /// Logs one heartbeat line with the current Accessibility state, without prompting.
    func heartbeat() {
        log("heartbeat, accessibility \(accessibilityTrusted(false) ? "granted" : "missing")")
    }
}
