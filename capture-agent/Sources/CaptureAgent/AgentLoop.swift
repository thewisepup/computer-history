import Foundation

/// The long-running agent that macOS starts at login.
public struct AgentLoop: Sendable {
    public static let heartbeatInterval: TimeInterval = 60
    public static let spoolFinishInterval: TimeInterval = 60

    let accessibilityTrusted: @Sendable (_ prompt: Bool) -> Bool
    let spool: SpoolWriter
    let counts: CaptureCounts
    let startCapturing: @Sendable () -> Void
    let log: @Sendable (String) -> Void

    public init(
        accessibilityTrusted: @escaping @Sendable (_ prompt: Bool) -> Bool,
        spool: SpoolWriter,
        counts: CaptureCounts,
        startCapturing: @escaping @Sendable () -> Void,
        log: @escaping @Sendable (String) -> Void
    ) {
        self.accessibilityTrusted = accessibilityTrusted
        self.spool = spool
        self.counts = counts
        self.startCapturing = startCapturing
        self.log = log
    }

    /// Starts once and, unless another agent holds the spool, starts capturing; then runs the heartbeat and the spool finish on the main run loop forever.
    public func run() -> Never {
        if start() { startCapturing() }
        Timer.scheduledTimer(withTimeInterval: Self.heartbeatInterval, repeats: true) { _ in
            heartbeat()
        }
        Timer.scheduledTimer(withTimeInterval: Self.spoolFinishInterval, repeats: true) { _ in
            finishSpoolFile()
        }
        RunLoop.main.run()
        fatalError("the main run loop returned")
    }

    /// Logs the Accessibility state, prompting if it is missing, readies the spool, and returns false if another agent holds it.
    @discardableResult
    func start() -> Bool {
        if accessibilityTrusted(true) {
            log("started, accessibility granted")
        } else {
            log("started, accessibility missing, asked macOS to prompt for it")
        }
        do {
            let leftover = try spool.start()
            log("spool ready at \(spool.directory.path)")
            if let leftover { log("spool finished leftover file \(leftover.lastPathComponent)") }
        } catch let error as SpoolWriter.InUse {
            log("spool failed to start at \(spool.directory.path): \(error), not capturing")
            return false
        } catch {
            log("spool failed to start at \(spool.directory.path): \(error)")
        }
        return true
    }

    /// Finishes the open spool file if it holds any records, logging any failure.
    func finishSpoolFile() {
        do {
            try spool.finish()
        } catch {
            log("spool failed to finish the open file: \(error)")
        }
    }

    /// Logs one heartbeat line with the Accessibility state, without prompting, and the capture counts since the last one.
    func heartbeat() {
        log("heartbeat, accessibility \(accessibilityTrusted(false) ? "granted" : "missing"), last minute: \(counts.take())")
    }
}
