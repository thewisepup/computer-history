import Foundation

final class CaptureLoop<M: Mac> {
    private var decision: CaptureDecision<M.Element>
    private let mac: M
    private let pause: PauseSwitch
    private let pollInterval: TimeInterval
    private let reader: WindowTextReader<M.Element>
    private let spool: any SpoolAppender
    private let screenshot: CaptureScreenshot<M>?
    private let counts: CaptureCounts
    private let log: (String) -> Void

    init(
        settings: AgentSettings,
        mac: M,
        spool: any SpoolAppender,
        images: any ImageStore,
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
        let screenshot = CaptureScreenshot(
            mac: mac,
            images: images,
            longEdge: settings.screenshots.longEdge,
            pause: settings.pause,
            idleThreshold: settings.capture.idleThreshold
        )
        self.screenshot = settings.screenshots.enabled ? screenshot : nil
        self.counts = counts
        self.log = log
    }

    func run(while keepGoing: () -> Bool) {
        while keepGoing() {
            let started = mac.uptime()
            tick()
            mac.sleep(max(0, started + pollInterval - mac.uptime()))
        }
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
            if write(SpoolRecord.excluded(at: mac.now(), trigger: trigger, appName: name(of: application), bundleID: application.bundleIdentifier)) {
                counts.recordExcluded()
            }
        case .capture(let application, let trigger):
            capture(application, trigger: trigger)
        }
    }

    private func capture(_ application: FocusedApplication, trigger: SpoolRecord.Trigger) {
        let capturedAt = mac.now()
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
        if let screenshot { _ = write(screenshot.take(for: record, of: application)) }
    }

    private func write(_ record: some SpoolLine) -> Bool {
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

/// Starts the thread that polls focus and captures through the given Mac for the life of the process.
public func startCaptureThread<M: Mac & Sendable>(
    mac: M,
    settings: AgentSettings,
    spool: SpoolWriter,
    images: JPEGImageStore,
    counts: CaptureCounts,
    log: @escaping @Sendable (String) -> Void
) {
    let thread = Thread {
        CaptureLoop(settings: settings, mac: mac, spool: spool, images: images, counts: counts, log: log).run { true }
    }
    thread.name = "capture"
    thread.stackSize = 8 << 20
    thread.start()
}
