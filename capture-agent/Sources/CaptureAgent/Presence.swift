import AppKit
import CoreGraphics

/// A reason the agent captures nothing: a pause, or the user away.
public enum Silence: String, CaseIterable, Sendable {
    case paused, idle, locked, asleep
}

/// The Mac going to sleep or waking.
public enum SleepChange: Sendable {
    case willSleep, didWake
}

/// Whether the user is at the Mac: seconds since the last input, and whether the screen is locked or the Mac asleep.
public struct Presence: Equatable, Sendable {
    public var idleSeconds: TimeInterval
    public var locked: Bool
    public var asleep: Bool

    public init(idleSeconds: TimeInterval, locked: Bool, asleep: Bool) {
        self.idleSeconds = idleSeconds
        self.locked = locked
        self.asleep = asleep
    }

    func silence(idleThreshold: TimeInterval) -> Set<Silence> {
        var reasons: Set<Silence> = []
        if idleSeconds > idleThreshold { reasons.insert(.idle) }
        if locked { reasons.insert(.locked) }
        if asleep { reasons.insert(.asleep) }
        return reasons
    }
}

/// Reads presence from macOS: seconds since the last input, the login session's lock state, and sleep and wake.
public final class LivePresence: @unchecked Sendable {
    private let sleep: SleepWatch
    private var observers: [any NSObjectProtocol] = []

    /// Starts listening for sleep and wake, which arrive on the main run loop.
    public init(log: AgentLog) {
        let sleep = SleepWatch(log: log)
        self.sleep = sleep
        let center = NSWorkspace.shared.notificationCenter
        observers = [
            center.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: nil) { _ in
                sleep.willSleep(at: ProcessInfo.processInfo.systemUptime, Date())
            },
            center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: nil) { _ in
                sleep.didWake(Date())
            },
        ]
    }

    /// Calls the handler on the main run loop as the Mac goes to sleep, before the Mac sleeps, and as it wakes from a sleep the handler recorded.
    public func onSleepChange(_ handler: @escaping @Sendable (SleepChange, Date) -> Bool) {
        sleep.onChange(handler)
    }

    deinit {
        observers.forEach(NSWorkspace.shared.notificationCenter.removeObserver)
    }

    public func sample() -> Presence {
        let session = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
        let locked = session["CGSSessionScreenIsLocked"] as? Bool == true
            || session[kCGSessionOnConsoleKey as String] as? Bool == false
        let anyInput = CGEventType(rawValue: ~0)!
        let idleSeconds = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: anyInput)
        let asleep = sleep.stillAsleep(idleSeconds: idleSeconds, uptime: ProcessInfo.processInfo.systemUptime)
        return Presence(idleSeconds: idleSeconds, locked: locked, asleep: asleep)
    }
}

func isStillAsleep(sleptAt: TimeInterval, idleSeconds: TimeInterval, uptime: TimeInterval) -> Bool {
    idleSeconds >= uptime - sleptAt
}
