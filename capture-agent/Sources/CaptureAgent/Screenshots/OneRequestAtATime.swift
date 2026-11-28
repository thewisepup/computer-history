import Foundation

/// Lets one request be outstanding at a time: while one has not answered, every other gets the fallback at once.
final class OneRequestAtATime: @unchecked Sendable {
    private let lock = NSLock()
    private let log: AgentLog
    private let category: AgentLog.Category
    private var state = RequestLatch.free

    init(log: AgentLog, _ category: AgentLog.Category) {
        self.log = log
        self.category = category
    }

    /// Starts the request and waits up to the timeout for its answer, or gives the fallback at once if an earlier request has not answered yet.
    func run<Answer: Sendable>(
        timeout: TimeInterval, otherwise fallback: Answer, _ start: (@escaping @Sendable (Answer) -> Void) -> Void
    ) -> Answer {
        let free = lock.withLock {
            guard case .free = state else { return false }
            return state.handle(.started(at: ProcessInfo.processInfo.systemUptime), log: log, category)
        }
        guard free else { return fallback }
        let result = PendingAnswer<Answer>()
        start { answer in
            _ = self.lock.withLock { self.state.handle(.answered, log: self.log, self.category) }
            result.finish(answer)
        }
        return result.wait(timeout: timeout) ?? fallback
    }
}

/// Whether a request is outstanding, and since which uptime.
enum RequestLatch: StateMachine {
    enum Event {
        case started(at: TimeInterval)
        case answered
    }

    static let name = "one request at a time"

    case free
    case outstanding(since: TimeInterval)

    func after(_ event: Event) -> RequestLatch? {
        switch (self, event) {
        case (.free, .started(let uptime)):
            .outstanding(since: uptime)
        case (.outstanding, .answered):
            .free
        case (.outstanding, .started), (.free, .answered):
            nil
        }
    }
}

/// An answer another thread gives once, waited for up to a timeout; later answers are ignored.
final class PendingAnswer<Answer: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private let done = DispatchSemaphore(value: 0)
    private var answer: Answer?

    func finish(_ answer: Answer) {
        lock.withLock { self.answer = self.answer ?? answer }
        done.signal()
    }

    func wait(timeout: TimeInterval) -> Answer? {
        guard done.wait(timeout: .now() + timeout) == .success else { return nil }
        return lock.withLock { answer }
    }
}
