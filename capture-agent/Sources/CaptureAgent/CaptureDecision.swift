import Foundation

/// What one tick of the capture thread does.
enum TickOutcome: Equatable {
    case nothing
    case paused
    case resumed
    case capture(FocusedApplication, SpoolRecord.Trigger)
    case excluded(FocusedApplication, SpoolRecord.Trigger)
}

/// Decides each tick from pausing, presence, the focused app and its window, and touches a window only when its app may be captured.
struct CaptureDecision<Element: AccessibilityElement> {
    private var schedule: CaptureSchedule
    private var apps: AppWatch
    private var windows: WindowWatch<Element>
    let denylist: Denylist
    private var recordedPaused: Bool

    var silence: Set<Silence> { schedule.silence }

    init(
        settings: CaptureSettings,
        denylist: Denylist,
        paused: Bool,
        apps: AppWatch,
        windows: WindowWatch<Element>,
        start: TimeInterval
    ) {
        schedule = CaptureSchedule(settings: settings, start: start)
        schedule.receive(.paused(paused), at: start)
        self.apps = apps
        self.windows = windows
        self.denylist = denylist
        recordedPaused = paused
    }

    /// Returns what this tick should write, polling focus only while capture is neither paused nor silent.
    mutating func tick(
        paused: Bool, presence: Presence, accessibilityTrusted: () -> Bool, at time: TimeInterval
    ) -> TickOutcome {
        schedule.receive(.presence(presence), at: time)
        schedule.receive(.paused(paused), at: time)
        if paused != recordedPaused { return paused ? .paused : .resumed }
        guard schedule.silence.isEmpty else { return .nothing }
        var change = apps.poll()
        guard let application = apps.application else { return .nothing }
        let excluded = denylist.contains(application)
        if excluded {
            windows.forget()
        } else if let windowChange = windows.poll(application) {
            change = change ?? windowChange
        }
        if let change { schedule.receive(.focusChanged(change), at: time) }
        guard excluded || accessibilityTrusted(), let trigger = schedule.takeDue(at: time) else { return .nothing }
        return excluded ? .excluded(application, trigger) : .capture(application, trigger)
    }

    /// Notes that a paused or resumed record reached the spool, so it is not offered again.
    mutating func recordedPause(_ paused: Bool) {
        recordedPaused = paused
    }
}
