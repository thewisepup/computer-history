import Foundation

/// Each tick samples presence, polls focus, and when a capture is due reads the focused window into the spool.
final class CaptureLoop<Element: AccessibilityElement> {
    private var schedule: CaptureSchedule
    private var focus: FocusWatch<Element>
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
        focus: FocusWatch<Element>,
        presence: @escaping () -> Presence,
        accessibilityTrusted: @escaping () -> Bool,
        read: @escaping (FocusedApplication) -> WindowText,
        spool: SpoolWriter,
        counts: CaptureCounts,
        uptime: @escaping () -> TimeInterval,
        now: @escaping () -> Date,
        log: @escaping (String) -> Void
    ) {
        self.schedule = CaptureSchedule(settings: settings, start: uptime())
        self.focus = focus
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
        let time = uptime()
        let silenceBefore = schedule.silence
        schedule.receive(.presence(presence()), at: time)
        if schedule.silence != silenceBefore { logSilence() }
        guard schedule.silence.isEmpty else { return }
        if let change = focus.poll() {
            schedule.receive(.focusChanged(change), at: time)
        }
        guard let application = focus.application, accessibilityTrusted(),
              let trigger = schedule.takeDue(at: time) else { return }
        let capturedAt = now()
        let started = uptime()
        let window = read(application)
        counts.recordRead(seconds: uptime() - started)
        do {
            try spool.append(record(of: application, window: window, trigger: trigger, at: capturedAt))
            counts.recordWritten(window)
        } catch {
            counts.recordFailed(error)
        }
    }

    private func record(
        of application: FocusedApplication, window: WindowText, trigger: SpoolRecord.Trigger, at capturedAt: Date
    ) -> SpoolRecord {
        .capture(
            at: capturedAt,
            trigger: trigger,
            appName: application.name ?? application.bundleIdentifier ?? "unknown",
            bundleID: application.bundleIdentifier,
            windowTitle: window.title,
            text: window.text,
            fullTextBytes: window.fullLength,
            timedOut: window.timedOut
        )
    }

    private func logSilence() {
        if schedule.silence.isEmpty {
            log("capturing again")
        } else {
            log("silent: " + Silence.allCases.filter(schedule.silence.contains).map(\.rawValue).joined(separator: ", "))
        }
    }
}

/// Starts the thread that polls focus and captures for the life of the process, reading through the live accessibility API.
public func startCaptureThread(
    settings: CaptureSettings,
    windowText: WindowTextSettings,
    spool: SpoolWriter,
    counts: CaptureCounts,
    log: @escaping @Sendable (String) -> Void
) {
    let presence = LivePresence()
    let thread = Thread {
        let uptime = { ProcessInfo.processInfo.systemUptime }
        let reader = WindowTextReader(settings: windowText)
        let loop = CaptureLoop(
            settings: settings,
            focus: FocusWatch(
                focusedApplication: { focusedApplication(callTimeout: windowText.callTimeout) },
                applicationElement: LiveAccessibilityElement.application
            ),
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
            Thread.sleep(forTimeInterval: max(0, started + settings.pollInterval - uptime()))
        }
    }
    thread.name = "capture"
    thread.stackSize = 8 << 20
    thread.start()
}
