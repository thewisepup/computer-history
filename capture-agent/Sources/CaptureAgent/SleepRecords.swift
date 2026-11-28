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

/// The Mac's sleep: awake, asleep since an uptime and whether its slept record was written, or waking until that sleep's woke record is written.
enum SleepState: StateMachine {
    enum Event {
        case willSleep(at: TimeInterval)
        case recorded(since: TimeInterval)
        case didWake
        case writingWoke(since: TimeInterval)
        case woke(since: TimeInterval)
    }

    static let name = "sleep"

    case awake
    case asleep(since: TimeInterval, recorded: Bool)
    case waking(since: TimeInterval, writing: Bool)

    func after(_ event: Event) -> SleepState? {
        switch (self, event) {
        case (_, .willSleep(let uptime)):
            .asleep(since: uptime, recorded: false)
        case (.asleep(let since, false), .recorded(let slept)) where since == slept:
            .asleep(since: since, recorded: true)
        case (.awake, .recorded(let slept)):
            .waking(since: slept, writing: false)
        case (.asleep(_, false), .didWake), (.awake, .didWake):
            .awake
        case (.asleep(let since, true), .didWake):
            .waking(since: since, writing: false)
        case (.waking, .didWake):
            self
        case (.waking(let since, false), .writingWoke(let slept)) where since == slept:
            .waking(since: since, writing: true)
        case (.waking(let since, true), .woke(let slept)) where since == slept:
            .awake
        default:
            nil
        }
    }
}

/// Tracks the Mac's sleep from macOS's sleep and wake and from input after a sleep, and tells one handler of each sleep and of the wake from each sleep it recorded.
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

    /// Writes the woke record a waking sleep still owes, then the new sleep's slept record, and its woke record at once if the Mac woke while that was written.
    func willSleep(at uptime: TimeInterval, _ time: Date) {
        let (handler, wokeOwed) = lock.withLock {
            let owed = if case .waking(_, false) = state { true } else { false }
            handle(.willSleep(at: uptime))
            return (changed, owed)
        }
        if wokeOwed { _ = handler(.didWake, time) }
        guard handler(.willSleep, time) else { return }
        let wokeMeanwhile = lock.withLock {
            handle(.recorded(since: uptime))
            return state == .waking(since: uptime, writing: false)
        }
        if wokeMeanwhile { finishWaking(since: uptime, Date()) }
    }

    func didWake(_ time: Date) {
        guard let since = lock.withLock({ beginWaking() }) else { return }
        finishWaking(since: since, time)
    }

    /// Whether the Mac is still asleep; input since the sleep wakes it, and its woke record is written later on the main queue.
    func stillAsleep(idleSeconds: TimeInterval, uptime: TimeInterval) -> Bool {
        let (asleep, waking) = lock.withLock {
            var waking: TimeInterval?
            if case .asleep(let since, _) = state, !isStillAsleep(sleptAt: since, idleSeconds: idleSeconds, uptime: uptime) {
                waking = beginWaking()
            }
            return (state != .awake, waking)
        }
        if let since = waking { DispatchQueue.main.async { self.finishWaking(since: since, Date()) } }
        return asleep
    }

    private func beginWaking() -> TimeInterval? {
        let recorded: TimeInterval? = if case .asleep(let since, true) = state { since } else { nil }
        handle(.didWake)
        return recorded
    }

    /// Writes the woke record once, only while that same sleep is still waking, and counts the Mac awake after it.
    private func finishWaking(since: TimeInterval, _ time: Date) {
        let handler: (@Sendable (SleepChange, Date) -> Bool)? = lock.withLock {
            guard state == .waking(since: since, writing: false) else { return nil }
            handle(.writingWoke(since: since))
            return changed
        }
        guard let handler else { return }
        _ = handler(.didWake, time)
        lock.withLock { handle(.woke(since: since)) }
    }

    private func handle(_ event: SleepState.Event) {
        state.handle(event, log: log, .capture)
    }
}
