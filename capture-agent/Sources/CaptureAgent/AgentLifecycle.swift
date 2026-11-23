import Foundation

/// The agent's start-up, then its minute timers on the main run loop: the log line and the spool finish; and its stop on SIGTERM.
public struct AgentLifecycle: Sendable {
    public static let logInterval: TimeInterval = 60
    public static let spoolFinishInterval: TimeInterval = 60
    public static let stopDrainSeconds: TimeInterval = 5

    let report: [String]
    let instanceLock: InstanceLock?
    let isPaused: @Sendable () -> Bool
    let accessibilityTrusted: @Sendable (_ prompt: Bool) -> Bool
    let spool: SpoolWriter
    let counts: CaptureCounts
    let startCapturing: @Sendable () -> Void
    let stopCapturing: @Sendable (_ deadline: DispatchTime) -> Int?
    let log: AgentLog

    public init(
        report: [String],
        instanceLock: InstanceLock?,
        isPaused: @escaping @Sendable () -> Bool,
        accessibilityTrusted: @escaping @Sendable (_ prompt: Bool) -> Bool,
        spool: SpoolWriter,
        counts: CaptureCounts,
        startCapturing: @escaping @Sendable () -> Void,
        stopCapturing: @escaping @Sendable (_ deadline: DispatchTime) -> Int?,
        log: AgentLog
    ) {
        self.report = report
        self.instanceLock = instanceLock
        self.isPaused = isPaused
        self.accessibilityTrusted = accessibilityTrusted
        self.spool = spool
        self.counts = counts
        self.startCapturing = startCapturing
        self.stopCapturing = stopCapturing
        self.log = log
    }

    /// Returns exit status 1 at once if another agent holds the instance lock or the spool; otherwise starts capturing and runs the minute log line and the spool finish on the main run loop until SIGTERM.
    public func run() -> Int32 {
        guard start() == .started else { return 1 }
        signal(SIGTERM, SIG_IGN)
        let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        terminate.setEventHandler {
            stop()
            exit(0)
        }
        terminate.resume()
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

    enum Start: Equatable {
        case started, instanceLockNotTaken, spoolHeldByAnotherAgent
    }

    @discardableResult
    func start() -> Start {
        if let instanceLock {
            do {
                try instanceLock.take()
            } catch {
                log.error(.lifecycle, "instance lock not taken at \(instanceLock.file.path): \(error), exiting")
                return .instanceLockNotTaken
            }
        }
        let spoolStart = Result { try spool.start() }
        if case .failure(let error as SpoolWriter.InUse) = spoolStart {
            log.error(.spool, "spool failed to start at \(spool.directory.path): \(error), exiting")
            return .spoolHeldByAnotherAgent
        }
        if accessibilityTrusted(true) {
            log.notice(.lifecycle, "started, accessibility granted")
        } else {
            log.notice(.lifecycle, "started, accessibility missing, asked macOS to prompt for it")
        }
        report.forEach { log.notice(.lifecycle, $0) }
        if isPaused() {
            log.notice(.lifecycle, "capture is paused, run `\(AgentIdentity.executableName) resume` to capture again")
        }
        switch spoolStart {
        case .success(let leftover):
            log.info(.spool, "spool ready at \(spool.directory.path)")
            if let leftover { log.info(.spool, "spool finished leftover file \(leftover.lastPathComponent)") }
        case .failure(let error):
            log.error(.spool, "spool failed to start at \(spool.directory.path): \(error)")
        }
        return .started
    }

    /// Stops capturing, gives queued screenshot records a few seconds to reach the spool, then finishes the spool's open file.
    func stop() {
        let dropped = stopCapturing(.now() + Self.stopDrainSeconds)
        finishSpoolFile()
        log.notice(.lifecycle, dropped.map { "stopping, \($0) screenshot records dropped" } ?? "stopping, the capture thread did not finish in time")
    }

    func finishSpoolFile() {
        do {
            try spool.finish()
        } catch {
            log.error(.spool, "spool failed to finish the open file: \(error)")
        }
    }

    func logMinute() {
        log.notice(.lifecycle, "heartbeat, accessibility \(accessibilityTrusted(false) ? "granted" : "missing"), last minute: \(counts.take())")
    }
}
