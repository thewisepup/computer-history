import Foundation

enum TickOutcome: Equatable {
    case nothing
    case paused
    case resumed
    case capture(FocusedApplication, SpoolRecord.Trigger)
    case excluded(FocusedApplication, SpoolRecord.Trigger)
}

/// Capture's pause: running, paused by the pause file with its paused record not written yet, paused, or resumed with its resumed record not written yet.
enum PauseState: StateMachine {
    enum Event {
        case fileSeen(paused: Bool)
        case recorded(paused: Bool)
    }

    static let name = "pause"

    case running
    case pausePending
    case paused
    case resumePending

    var silencesCapture: Bool {
        switch self {
        case .pausePending, .paused: true
        case .running, .resumePending: false
        }
    }

    func after(_ event: Event) -> PauseState? {
        switch (self, event) {
        case (.running, .fileSeen(false)), (.pausePending, .fileSeen(false)), (.resumePending, .recorded(paused: false)):
            .running
        case (.running, .fileSeen(true)), (.pausePending, .fileSeen(true)):
            .pausePending
        case (.paused, .fileSeen(true)), (.resumePending, .fileSeen(true)), (.pausePending, .recorded(paused: true)):
            .paused
        case (.paused, .fileSeen(false)), (.resumePending, .fileSeen(false)):
            .resumePending
        case (.running, .recorded), (.paused, .recorded), (.pausePending, .recorded(paused: false)),
             (.resumePending, .recorded(paused: true)):
            nil
        }
    }
}

struct CaptureDecision<Element: AccessibilityElement> {
    private var schedule: CaptureSchedule
    private var apps: AppWatch
    private var windows: WindowWatch<Element>
    let denylist: Denylist
    private(set) var pause: PauseState
    private let log: AgentLog

    var silence: Set<Silence> { schedule.silence }

    init(
        settings: CaptureSettings,
        denylist: Denylist,
        paused: Bool,
        apps: AppWatch,
        windows: WindowWatch<Element>,
        start: TimeInterval,
        log: AgentLog
    ) {
        schedule = CaptureSchedule(settings: settings, start: start)
        pause = paused ? .paused : .running
        schedule.receive(.paused(pause.silencesCapture), at: start)
        self.apps = apps
        self.windows = windows
        self.denylist = denylist
        self.log = log
    }

    mutating func tick(
        paused: Bool, presence: Presence, accessibilityTrusted: () -> Bool, at time: TimeInterval
    ) -> TickOutcome {
        pause.handle(.fileSeen(paused: paused), log: log, .capture)
        schedule.receive(.presence(presence), at: time)
        schedule.receive(.paused(pause.silencesCapture), at: time)
        switch pause {
        case .pausePending: return .paused
        case .resumePending: return .resumed
        case .running, .paused: break
        }
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

    mutating func recordedPause(_ paused: Bool) {
        pause.handle(.recorded(paused: paused), log: log, .capture)
    }
}
