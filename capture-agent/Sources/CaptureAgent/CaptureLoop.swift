import Foundation

final class CaptureLoop<M: Mac> {
    private var decision: CaptureDecision<M.Element>
    private let mac: M
    private let pause: PauseSwitch
    private let pollInterval: TimeInterval
    private let reader: WindowTextReader<M.Element>
    private let spool: any SpoolAppender
    private var screenshots: (stage: CaptureScreenshot<M>, queue: ScreenshotQueue)?
    private let counts: CaptureCounts
    private let log: (String) -> Void

    init(
        settings: AgentSettings,
        mac: M,
        spool: any SpoolAppender,
        images: any ImageStore,
        recognize: @escaping @Sendable (URL) throws -> String,
        counts: CaptureCounts,
        log: @escaping (String) -> Void
    ) {
        self.decision = CaptureDecision(
            settings: settings.capture,
            denylist: settings.denylist,
            paused: settings.pause.isPaused,
            apps: AppWatch(
                focusedApplication: mac.focusedApplication,
                frontmostApplication: mac.frontmostApplication,
                denylist: settings.denylist
            ),
            windows: WindowWatch(applicationElement: mac.applicationElement),
            start: mac.uptime()
        )
        self.mac = mac
        self.pause = settings.pause
        self.pollInterval = settings.capture.pollInterval
        self.reader = WindowTextReader(
            settings: settings.windowText,
            applicationElement: mac.applicationElement,
            hasElectronFramework: mac.hasElectronFramework,
            now: mac.uptime
        )
        self.spool = spool
        if settings.screenshots.enabled {
            let stage = CaptureScreenshot(
                mac: mac,
                images: images,
                longEdge: settings.screenshots.longEdge,
                pause: settings.pause,
                idleThreshold: settings.capture.idleThreshold,
                dedup: ScreenshotDedup(changePixels: settings.screenshots.changePixels, keepAfter: settings.screenshots.keepAfter),
                reminder: PermissionReminder(file: settings.permissionReminderFile),
                log: log
            )
            let queue = ScreenshotQueue(
                recognize: recognize,
                capBytes: settings.windowText.textCapBytes,
                timeout: settings.screenshots.recognitionTimeout,
                spool: spool,
                counts: counts
            )
            self.screenshots = (stage, queue)
        }
        self.counts = counts
        self.log = log
        mac.onSleepChange(SleepRecords(spool: spool, pause: settings.pause, counts: counts).receive)
    }

    func run(while keepGoing: () -> Bool) {
        while keepGoing() {
            let started = mac.uptime()
            tick()
            mac.sleep(max(0, started + pollInterval - mac.uptime()))
        }
    }

    /// Waits until the screenshot record of every capture so far has been written or refused.
    func waitForScreenshots() {
        screenshots?.queue.waitUntilWritten()
    }

    /// Gives queued screenshot records until the deadline to reach the spool, then writes no more, and returns how many were dropped.
    func stopScreenshots(by deadline: DispatchTime) -> Int {
        screenshots?.queue.stop(by: deadline) ?? 0
    }

    func tick() {
        let silenceBefore = decision.silence
        let outcome = decision.tick(
            paused: pause.isPaused, presence: mac.samplePresence(), accessibilityTrusted: mac.accessibilityTrusted, at: mac.uptime()
        )
        if decision.silence != silenceBefore { logSilence() }
        switch outcome {
        case .nothing:
            return
        case .paused:
            if write(SpoolRecord.paused(at: mac.now())) { decision.recordedPause(true) }
        case .resumed:
            if write(SpoolRecord.resumed(at: mac.now())) { decision.recordedPause(false) }
        case .excluded(let application, let trigger):
            let excludedAt = mac.now()
            guard !mac.samplePresence().asleep else { return }
            if write(SpoolRecord.excluded(at: excludedAt, trigger: trigger, appName: name(of: application), bundleID: application.bundleIdentifier)) {
                counts.recordExcluded()
            }
        case .capture(let application, let trigger):
            capture(application, trigger: trigger)
        }
    }

    /// Writes nothing if the Mac fell asleep after the tick sampled presence, so no record is later than its slept record.
    private func capture(_ application: FocusedApplication, trigger: SpoolRecord.Trigger) {
        let capturedAt = mac.now()
        guard !mac.samplePresence().asleep else { return }
        let started = mac.uptime()
        let window = reader.read(application)
        counts.recordRead(seconds: mac.uptime() - started)
        let record = SpoolRecord.capture(
            at: capturedAt,
            trigger: trigger,
            appName: name(of: application),
            bundleID: application.bundleIdentifier,
            windowTitle: window.title,
            text: window.text,
            fullTextBytes: window.fullLength,
            timedOut: window.timedOut
        )
        guard write(record) else { return }
        counts.recordWritten(record)
        guard let shot = screenshots?.stage.take(for: record, of: application) else { return }
        screenshots?.queue.add(shot)
    }

    private func write(_ record: SpoolRecord) -> Bool {
        do {
            try spool.append(record)
            return true
        } catch {
            counts.recordFailed(error)
            return false
        }
    }

    private func name(of application: FocusedApplication) -> String {
        application.name ?? application.bundleIdentifier ?? "unknown"
    }

    private func logSilence() {
        if decision.silence.isEmpty {
            log("capturing again")
        } else {
            log("silent: " + Silence.allCases.filter(decision.silence.contains).map(\.rawValue).joined(separator: ", "))
        }
    }
}

/// Asks the capture thread to stop capturing and waits for it to give its screenshot records until a deadline.
public final class CaptureStop: @unchecked Sendable {
    public static let grace: TimeInterval = 1

    private let lock = NSLock()
    private let finished = DispatchSemaphore(value: 0)
    private var deadline: DispatchTime?
    private var dropped = 0

    public init() {}

    var requestedDeadline: DispatchTime? { lock.withLock { deadline } }

    /// Stops new captures and returns how many screenshot records were dropped at the deadline, or nil if the capture thread had not finished a second after it.
    public func stop(by deadline: DispatchTime) -> Int? {
        lock.withLock { self.deadline = deadline }
        guard finished.wait(timeout: deadline + Self.grace) == .success else { return nil }
        return lock.withLock { dropped }
    }

    func finish(dropped: Int) {
        lock.withLock { self.dropped = dropped }
        finished.signal()
    }
}

/// Starts the thread that polls focus and captures through the given Mac, saving and reading screenshots with the given store and recognizer, until asked to stop.
public func startCaptureThread<M: Mac & Sendable>(
    mac: M,
    settings: AgentSettings,
    spool: SpoolWriter,
    images: JPEGImageStore,
    recognize: @escaping @Sendable (URL) throws -> String,
    counts: CaptureCounts,
    stop: CaptureStop,
    log: @escaping @Sendable (String) -> Void
) {
    let thread = Thread {
        let loop = CaptureLoop(settings: settings, mac: mac, spool: spool, images: images, recognize: recognize, counts: counts, log: log)
        loop.run { stop.requestedDeadline == nil }
        stop.finish(dropped: loop.stopScreenshots(by: stop.requestedDeadline ?? .now()))
    }
    thread.name = "capture"
    thread.stackSize = 8 << 20
    thread.start()
}
