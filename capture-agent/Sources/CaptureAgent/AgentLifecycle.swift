import Foundation

/// The agent's start-up, then its minute timers on the main run loop: the log line and the spool finish.
public struct AgentLifecycle: Sendable {
    public static let logInterval: TimeInterval = 60
    public static let spoolFinishInterval: TimeInterval = 60

    let report: [String]
    let isPaused: @Sendable () -> Bool
    let accessibilityTrusted: @Sendable (_ prompt: Bool) -> Bool
    let spool: SpoolWriter
    let counts: CaptureCounts
    let startCapturing: @Sendable () -> Void
    let log: @Sendable (String) -> Void

    public init(
        report: [String],
        isPaused: @escaping @Sendable () -> Bool,
        accessibilityTrusted: @escaping @Sendable (_ prompt: Bool) -> Bool,
        spool: SpoolWriter,
        counts: CaptureCounts,
        startCapturing: @escaping @Sendable () -> Void,
        log: @escaping @Sendable (String) -> Void
    ) {
        self.report = report
        self.isPaused = isPaused
        self.accessibilityTrusted = accessibilityTrusted
        self.spool = spool
        self.counts = counts
        self.startCapturing = startCapturing
        self.log = log
    }

    /// Returns exit status 1 at once if another agent holds the spool; otherwise starts capturing and runs the minute log line and the spool finish on the main run loop forever.
    public func run() -> Int32 {
        guard start() else { return 1 }
        startCapturing()
        Timer.scheduledTimer(withTimeInterval: Self.logInterval, repeats: true) { _ in
            logMinute()
        }
        Timer.scheduledTimer(withTimeInterval: Self.spoolFinishInterval, repeats: true) { _ in
            finishSpoolFile()
        }
        RunLoop.main.run()
        fatalError("the main run loop returned")
    }

    /// Logs the Accessibility state, prompting if it is missing, then the settings report and pause state, readies the spool, and returns false if another agent holds it.
    @discardableResult
    func start() -> Bool {
        if accessibilityTrusted(true) {
            log("started, accessibility granted")
        } else {
            log("started, accessibility missing, asked macOS to prompt for it")
        }
        report.forEach(log)
        if isPaused() {
            log("capture is paused, run `\(AgentIdentity.executableName) resume` to capture again")
        }
        do {
            let leftover = try spool.start()
            log("spool ready at \(spool.directory.path)")
            if let leftover { log("spool finished leftover file \(leftover.lastPathComponent)") }
        } catch let error as SpoolWriter.InUse {
            log("spool failed to start at \(spool.directory.path): \(error), exiting")
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

    /// Logs the minute's line with the Accessibility state, without prompting, and the capture counts since the last one.
    func logMinute() {
        log("heartbeat, accessibility \(accessibilityTrusted(false) ? "granted" : "missing"), last minute: \(counts.take())")
    }
}
