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

private let precedence: [FocusChange] = [.app, .window, .title]

struct CaptureSchedule {
    enum Event: Equatable {
        case presence(Presence)
        case paused(Bool)
        case focusChanged(FocusChange)
    }

    /// A focus change waiting to settle: the strongest change seen, when the first arrived, and when the last one settles.
    struct PendingChange: Equatable {
        let change: FocusChange
        let since: TimeInterval
        let settledAt: TimeInterval
    }

    private enum PendingEvent {
        case changed(FocusChange, at: TimeInterval)
        case dropped
    }

    let settings: CaptureSettings
    private(set) var silence: Set<Silence> = []
    private(set) var pending: PendingChange?
    private var heartbeatDue: TimeInterval
    private var lastCapture: TimeInterval?

    init(settings: CaptureSettings, start: TimeInterval) {
        self.settings = settings
        heartbeatDue = start + settings.settleDelay
    }

    mutating func receive(_ event: Event, at now: TimeInterval) {
        switch event {
        case .presence(let presence):
            let paused: Set<Silence> = silence.contains(.paused) ? [.paused] : []
            updateSilence(presence.silence(idleThreshold: settings.idleThreshold).union(paused), at: now)
        case .paused(let paused):
            updateSilence(paused ? silence.union([.paused]) : silence.subtracting([.paused]), at: now)
        case .focusChanged(let change):
            guard silence.isEmpty else { return }
            movePending(.changed(change, at: now))
        }
    }

    private mutating func movePending(_ event: PendingEvent) {
        switch (pending, event) {
        case (nil, .changed(let change, let now)):
            pending = PendingChange(change: change, since: now, settledAt: now + settings.settleDelay)
        case (let waiting?, .changed(let change, let now)):
            let strongest = precedence.first { $0 == waiting.change || $0 == change } ?? waiting.change
            pending = PendingChange(change: strongest, since: waiting.since, settledAt: now + settings.settleDelay)
        case (nil, .dropped), (_?, .dropped):
            pending = nil
        }
    }

    private mutating func updateSilence(_ reasons: Set<Silence>, at now: TimeInterval) {
        let wasSilent = !silence.isEmpty
        silence = reasons
        if !silence.isEmpty {
            movePending(.dropped)
        } else if wasSilent {
            heartbeatDue = now + settings.settleDelay
        }
    }

    mutating func takeDue(at now: TimeInterval) -> SpoolRecord.Trigger? {
        guard silence.isEmpty else { return nil }
        if let lastCapture, now < lastCapture + settings.minimumGap { return nil }
        let trigger: SpoolRecord.Trigger
        if let pending {
            guard now >= pending.settledAt || now >= pending.since + settings.heartbeatInterval else { return nil }
            trigger = pending.change.trigger
        } else {
            guard now >= heartbeatDue else { return nil }
            trigger = .heartbeat
        }
        movePending(.dropped)
        lastCapture = now
        heartbeatDue = now + settings.heartbeatInterval
        return trigger
    }
}
