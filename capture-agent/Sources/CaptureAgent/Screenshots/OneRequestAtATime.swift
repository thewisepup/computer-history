import Foundation

/// Lets one request be outstanding at a time: while one has not answered, every other gets the fallback at once.
final class OneRequestAtATime: @unchecked Sendable {
    private let lock = NSLock()
    private var outstanding = false

    /// Starts the request and waits up to the timeout for its answer, or gives the fallback at once if an earlier request has not answered yet.
    func run<Answer: Sendable>(
        timeout: TimeInterval, otherwise fallback: Answer, _ start: (@escaping @Sendable (Answer) -> Void) -> Void
    ) -> Answer {
        let free = lock.withLock {
            defer { outstanding = true }
            return !outstanding
        }
        guard free else { return fallback }
        let result = PendingAnswer<Answer>()
        start { answer in
            self.lock.withLock { self.outstanding = false }
            result.finish(answer)
        }
        return result.wait(timeout: timeout) ?? fallback
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
