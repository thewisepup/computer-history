import Foundation

/// How often the agent captures, how long it waits after a switch, and when it counts the user as idle.
public struct CaptureSettings: Equatable, Sendable {
    public var idleThreshold: TimeInterval
    public var heartbeatInterval: TimeInterval
    public var settleDelay: TimeInterval
    public var minimumGap: TimeInterval
    public var pollInterval: TimeInterval

    public init(
        idleThreshold: TimeInterval = 180,
        heartbeatInterval: TimeInterval = 30,
        settleDelay: TimeInterval = 1,
        minimumGap: TimeInterval = 1,
        pollInterval: TimeInterval = 0.5
    ) {
        self.idleThreshold = idleThreshold
        self.heartbeatInterval = heartbeatInterval
        self.settleDelay = settleDelay
        self.minimumGap = minimumGap
        self.pollInterval = pollInterval
    }
}

private let precedence: [SpoolRecord.Trigger] = [.app, .window, .title, .heartbeat]

/// Decides when to capture from focus changes, presence samples and the passing time.
struct CaptureSchedule {
    enum Event: Equatable {
        case presence(Presence)
        case focusChanged(SpoolRecord.Trigger)
    }

    let settings: CaptureSettings
    private(set) var silence: Set<Silence> = []
    private var pending: SpoolRecord.Trigger?
    private var pendingSince: TimeInterval = 0
    private var settledAt: TimeInterval = 0
    private var heartbeatDue: TimeInterval
    private var lastCapture: TimeInterval?

    init(settings: CaptureSettings, start: TimeInterval) {
        self.settings = settings
        heartbeatDue = start + settings.settleDelay
    }

    mutating func receive(_ event: Event, at now: TimeInterval) {
        switch event {
        case .presence(let presence):
            let wasSilent = !silence.isEmpty
            silence = presence.silence(idleThreshold: settings.idleThreshold)
            if !silence.isEmpty {
                pending = nil
            } else if wasSilent {
                heartbeatDue = now + settings.settleDelay
            }
        case .focusChanged(let trigger):
            guard silence.isEmpty else { return }
            if let pending {
                self.pending = precedence.first { $0 == pending || $0 == trigger }
            } else {
                pending = trigger
                pendingSince = now
            }
            settledAt = now + settings.settleDelay
        }
    }

    /// Returns the trigger of the capture due now and counts it as taken, or nil if none is due.
    mutating func takeDue(at now: TimeInterval) -> SpoolRecord.Trigger? {
        guard silence.isEmpty else { return nil }
        if let lastCapture, now < lastCapture + settings.minimumGap { return nil }
        let trigger: SpoolRecord.Trigger
        if let pending {
            guard now >= settledAt || now >= pendingSince + settings.heartbeatInterval else { return nil }
            trigger = pending
        } else {
            guard now >= heartbeatDue else { return nil }
            trigger = .heartbeat
        }
        pending = nil
        lastCapture = now
        heartbeatDue = now + settings.heartbeatInterval
        return trigger
    }
}
