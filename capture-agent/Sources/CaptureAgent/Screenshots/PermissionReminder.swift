import Foundation

/// The once-a-day reminder that the Screen Recording grant is missing, with the time of the last one shown kept in a file.
struct PermissionReminder {
    static let interval: TimeInterval = 24 * 60 * 60

    /// A warning the reminder logs once per run at most.
    enum Warning {
        case unavailable, unsaved
    }

    /// Whether a reminder was tried, and when.
    enum State: Equatable {
        case notTried
        case tried(at: Date)

        enum Event {
            case tried(at: Date)
            case grantSeen
        }

        mutating func handle(_ event: Event) {
            switch (self, event) {
            case (.notTried, .tried(let time)), (.tried, .tried(let time)):
                self = .tried(at: time)
            case (.notTried, .grantSeen), (.tried, .grantSeen):
                self = .notTried
            }
        }
    }

    private let file: URL
    private(set) var state: State
    private var told: Set<Warning> = []

    init(file: URL) {
        self.file = file
        let saved = (try? String(contentsOf: file, encoding: .utf8)).flatMap {
            try? Date($0.trimmingCharacters(in: .whitespacesAndNewlines), strategy: .iso8601)
        }
        state = saved.map { .tried(at: $0) } ?? .notTried
    }

    /// Posts the reminder when none was tried in the last day, saving the time only once one was posted, which may happen later on another thread once the user allows notifications.
    mutating func grantMissing(
        at now: Date, post: (UserNotification, @escaping @Sendable () -> Void) -> NotificationPosting, log: AgentLog
    ) {
        if case .tried(let lastTried) = state, (-Self.interval..<Self.interval).contains(now.timeIntervalSince(lastTried)) { return }
        state.handle(.tried(at: now))
        switch post(ScreenRecordingSettings.reminder, { [file] in try? Self.write(now, to: file) }) {
        case .posted:
            log.notice(.screenshots, "screen recording missing, posted a reminder")
            save(now, log: log)
        case .awaitingPermission:
            log.notice(.screenshots, "screen recording missing, asked macOS to allow notifications for the reminder")
        case .timedOut(let seconds):
            log.notice(.screenshots, "screen recording missing, the notification centre did not answer within \(Int(seconds))s")
        case .unavailable(let reason):
            guard told.insert(.unavailable).inserted else { return }
            log.notice(.screenshots, "screen recording missing, notifications unavailable (\(reason)), status is the only warning")
        }
    }

    /// Forgets the last reminder once a screenshot shows the grant is held.
    mutating func grantSeen() {
        guard case .tried = state else { return }
        state.handle(.grantSeen)
        try? FileManager.default.removeItem(at: file)
    }

    private mutating func save(_ time: Date, log: AgentLog) {
        do {
            try Self.write(time, to: file)
        } catch {
            guard told.insert(.unsaved).inserted else { return }
            log.error(.screenshots, "could not save the reminder time to \(file.path) (\(error.localizedDescription)), a restart may remind again")
        }
    }

    private static func write(_ time: Date, to file: URL) throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data((time.formatted(.iso8601) + "\n").utf8).write(to: file, options: .atomic)
    }
}
