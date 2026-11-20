import Foundation

/// The once-a-day reminder that the Screen Recording grant is missing, with the time of the last one shown kept in a file.
struct PermissionReminder {
    static let interval: TimeInterval = 24 * 60 * 60

    private let file: URL
    private var lastTried: Date?
    private var toldUnavailable = false
    private var toldUnsaved = false

    init(file: URL) {
        self.file = file
        lastTried = (try? String(contentsOf: file, encoding: .utf8)).flatMap {
            try? Date($0.trimmingCharacters(in: .whitespacesAndNewlines), strategy: .iso8601)
        }
    }

    /// Posts the reminder when none was tried in the last day, saving the time only once one was posted, which may happen later on another thread once the user allows notifications.
    mutating func grantMissing(
        at now: Date, post: (UserNotification, @escaping @Sendable () -> Void) -> NotificationPosting, log: (String) -> Void
    ) {
        if let lastTried, (-Self.interval..<Self.interval).contains(now.timeIntervalSince(lastTried)) { return }
        lastTried = now
        switch post(ScreenRecordingSettings.reminder, { [file] in try? Self.write(now, to: file) }) {
        case .posted:
            log("screen recording missing, posted a reminder")
            save(now, log: log)
        case .awaitingPermission:
            log("screen recording missing, asked macOS to allow notifications for the reminder")
        case .timedOut(let seconds):
            log("screen recording missing, the notification centre did not answer within \(Int(seconds))s")
        case .unavailable(let reason):
            guard !toldUnavailable else { return }
            toldUnavailable = true
            log("screen recording missing, notifications unavailable (\(reason)), status is the only warning")
        }
    }

    /// Forgets the last reminder once a screenshot shows the grant is held.
    mutating func grantSeen() {
        guard lastTried != nil else { return }
        lastTried = nil
        try? FileManager.default.removeItem(at: file)
    }

    private mutating func save(_ time: Date, log: (String) -> Void) {
        do {
            try Self.write(time, to: file)
        } catch {
            guard !toldUnsaved else { return }
            toldUnsaved = true
            log("could not save the reminder time to \(file.path) (\(error.localizedDescription)), a restart may remind again")
        }
    }

    private static func write(_ time: Date, to file: URL) throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data((time.formatted(.iso8601) + "\n").utf8).write(to: file, options: .atomic)
    }
}
