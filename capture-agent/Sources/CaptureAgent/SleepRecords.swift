import Foundation

/// Writes a slept record as the Mac goes to sleep and a woke record as it wakes, returning whether it wrote one; nothing while capture is paused.
struct SleepRecords: Sendable {
    let pause: PauseSwitch
    let writer: RecordWriter

    func receive(_ change: SleepChange, at time: Date) -> Bool {
        switch change {
        case .willSleep:
            guard !pause.isPaused else { return false }
            return writer.write(.slept(at: time))
        case .didWake:
            return writer.write(.woke(at: time))
        }
    }
}

/// The Mac's sleep: awake, asleep since an uptime and whether that sleep was recorded, or waking while its woke record is written.
enum SleepState: StateMachine {
    enum Event {
        case willSleep(at: TimeInterval)
        case recorded
        case didWake
        case woke
    }

    static let name = "sleep"

    case awake
    case asleep(since: TimeInterval, recorded: Bool)
    case waking

    func after(_ event: Event) -> SleepState? {
        switch (self, event) {
        case (.awake, .willSleep(let uptime)), (.asleep, .willSleep(let uptime)), (.waking, .willSleep(let uptime)):
            .asleep(since: uptime, recorded: false)
        case (.asleep(let since, false), .recorded):
            .asleep(since: since, recorded: true)
        case (.asleep(_, false), .didWake), (.awake, .didWake):
            .awake
        case (.asleep(_, true), .didWake), (.waking, .didWake):
            .waking
        case (.waking, .woke):
            .awake
        case (.awake, .recorded), (.asleep(_, true), .recorded), (.waking, .recorded), (.awake, .woke), (.asleep, .woke):
            nil
        }
    }
}

/// Holds the Mac's sleep, moved by sleep and wake from macOS or by input after a sleep, and passes each sleep and the wake from a recorded one to one handler.
final class SleepWatch: @unchecked Sendable {
    private let lock = NSLock()
    private let log: AgentLog
    private var state = SleepState.awake
    private var changed: @Sendable (SleepChange, Date) -> Bool = { _, _ in false }

    init(log: AgentLog) {
        self.log = log
    }

    var current: SleepState { lock.withLock { state } }

    func onChange(_ handler: @escaping @Sendable (SleepChange, Date) -> Bool) {
        lock.withLock { changed = handler }
    }

    func willSleep(at uptime: TimeInterval, _ time: Date) {
        let handler = lock.withLock {
            handle(.willSleep(at: uptime))
            return changed
        }
        guard handler(.willSleep, time) else { return }
        lock.withLock { handle(.recorded) }
    }

    func didWake(_ time: Date) {
        guard lock.withLock({ beginWaking() }) else { return }
        finishWaking(time)
    }

    /// Whether the Mac is still asleep, waking it once input has arrived since it slept and writing that wake's record later on the main queue.
    func stillAsleep(idleSeconds: TimeInterval, uptime: TimeInterval) -> Bool {
        let (asleep, waking) = lock.withLock {
            var waking = false
            if case .asleep(let since, _) = state, !isStillAsleep(sleptAt: since, idleSeconds: idleSeconds, uptime: uptime) {
                waking = beginWaking()
            }
            return (state != .awake, waking)
        }
        if waking { DispatchQueue.main.async { self.finishWaking(Date()) } }
        return asleep
    }

    private func beginWaking() -> Bool {
        let recorded = if case .asleep(_, true) = state { true } else { false }
        handle(.didWake)
        return recorded
    }

    private func finishWaking(_ time: Date) {
        _ = lock.withLock { changed }(.didWake, time)
        lock.withLock { handle(.woke) }
    }

    private func handle(_ event: SleepState.Event) {
        state.handle(event, log: log, .capture)
    }
}
