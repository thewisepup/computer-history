import Foundation

/// The long-running agent that macOS starts at login.
public struct AgentLoop: Sendable {
    public static let heartbeatInterval: TimeInterval = 60
    public static let spoolFinishInterval: TimeInterval = 60

    let accessibilityTrusted: @Sendable (_ prompt: Bool) -> Bool
    let spool: SpoolWriter
    let log: @Sendable (String) -> Void

    public init(
        accessibilityTrusted: @escaping @Sendable (_ prompt: Bool) -> Bool,
        spool: SpoolWriter,
        log: @escaping @Sendable (String) -> Void
    ) {
        self.accessibilityTrusted = accessibilityTrusted
        self.spool = spool
        self.log = log
    }

    /// Starts once, then runs the heartbeat and the spool finish on the main run loop forever.
    public func run() -> Never {
        start()
        Timer.scheduledTimer(withTimeInterval: Self.heartbeatInterval, repeats: true) { _ in
            heartbeat()
        }
        Timer.scheduledTimer(withTimeInterval: Self.spoolFinishInterval, repeats: true) { _ in
            finishSpoolFile()
        }
        RunLoop.main.run()
        fatalError("the main run loop returned")
    }

    /// Logs whether Accessibility is granted and asks macOS to prompt for it if not, then readies the spool.
    func start() {
        if accessibilityTrusted(true) {
            log("started, accessibility granted")
        } else {
            log("started, accessibility missing, asked macOS to prompt for it")
        }
        do {
            let leftover = try spool.start()
            log("spool ready at \(spool.directory.path)")
            if let leftover { log("spool finished leftover file \(leftover.lastPathComponent)") }
        } catch {
            log("spool failed to start at \(spool.directory.path): \(error)")
        }
    }

    /// Finishes the open spool file if it holds any records, logging any failure.
    func finishSpoolFile() {
        do {
            try spool.finish()
        } catch {
            log("spool failed to finish the open file: \(error)")
        }
    }

    /// Logs one heartbeat line with the current Accessibility state, without prompting.
    func heartbeat() {
        log("heartbeat, accessibility \(accessibilityTrusted(false) ? "granted" : "missing")")
    }
}
