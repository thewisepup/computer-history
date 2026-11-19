import Foundation

/// Each tick asks the capture decision what to do, then reads the focused window or writes a gap record into the spool.
final class CaptureLoop<Element: AccessibilityElement> {
    private var decision: CaptureDecision<Element>
    private let isPaused: () -> Bool
    private let presence: () -> Presence
    private let accessibilityTrusted: () -> Bool
    private let read: (FocusedApplication) -> WindowText
    private let spool: SpoolWriter
    private let counts: CaptureCounts
    private let uptime: () -> TimeInterval
    private let now: () -> Date
    private let log: (String) -> Void

    init(
        settings: CaptureSettings,
        denylist: Denylist,
        apps: AppWatch,
        windows: WindowWatch<Element>,
        isPaused: @escaping () -> Bool,
        presence: @escaping () -> Presence,
        accessibilityTrusted: @escaping () -> Bool,
        read: @escaping (FocusedApplication) -> WindowText,
        spool: SpoolWriter,
        counts: CaptureCounts,
        uptime: @escaping () -> TimeInterval,
        now: @escaping () -> Date,
        log: @escaping (String) -> Void
    ) {
        self.decision = CaptureDecision(
            settings: settings, denylist: denylist, paused: isPaused(), apps: apps, windows: windows, start: uptime()
        )
        self.isPaused = isPaused
        self.presence = presence
        self.accessibilityTrusted = accessibilityTrusted
        self.read = read
        self.spool = spool
        self.counts = counts
        self.uptime = uptime
        self.now = now
        self.log = log
    }

    func tick() {
        let silenceBefore = decision.silence
        let outcome = decision.tick(
            paused: isPaused(), presence: presence(), accessibilityTrusted: accessibilityTrusted, at: uptime()
        )
        if decision.silence != silenceBefore { logSilence() }
        switch outcome {
        case .nothing:
            return
        case .paused:
            if write(.paused(at: now())) { decision.recordedPause(true) }
        case .resumed:
            if write(.resumed(at: now())) { decision.recordedPause(false) }
        case .excluded(let application, let trigger):
            if write(.excluded(at: now(), trigger: trigger, appName: name(of: application), bundleID: application.bundleIdentifier)) {
                counts.recordExcluded()
            }
        case .capture(let application, let trigger):
            capture(application, trigger: trigger)
        }
    }

    private func capture(_ application: FocusedApplication, trigger: SpoolRecord.Trigger) {
        let capturedAt = now()
        let started = uptime()
        let window = read(application)
        counts.recordRead(seconds: uptime() - started)
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
        if write(record) { counts.recordWritten(window) }
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

/// Starts the thread that polls focus and captures for the life of the process, reading through the live accessibility API.
public func startCaptureThread(
    settings: AgentSettings,
    spool: SpoolWriter,
    counts: CaptureCounts,
    log: @escaping @Sendable (String) -> Void
) {
    LiveAccessibilityElement.setProcessCallTimeout(settings.windowText.callTimeout)
    let presence = LivePresence()
    let pause = settings.pause
    let thread = Thread {
        let uptime = { ProcessInfo.processInfo.systemUptime }
        let reader = WindowTextReader(settings: settings.windowText)
        let loop = CaptureLoop(
            settings: settings.capture,
            denylist: settings.denylist,
            apps: AppWatch(focusedApplication: focusedApplication),
            windows: WindowWatch(applicationElement: LiveAccessibilityElement.application),
            isPaused: { pause.isPaused },
            presence: presence.sample,
            accessibilityTrusted: { isAccessibilityTrusted(prompt: false) },
            read: reader.read,
            spool: spool,
            counts: counts,
            uptime: uptime,
            now: Date.init,
            log: log
        )
        while true {
            let started = uptime()
            loop.tick()
            Thread.sleep(forTimeInterval: max(0, started + settings.capture.pollInterval - uptime()))
        }
    }
    thread.name = "capture"
    thread.stackSize = 8 << 20
    thread.start()
}
