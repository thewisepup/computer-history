import Foundation

/// The once-a-day rule for reminding that the Screen Recording grant is missing, with the last reminder's time kept in a file so the rule holds across restarts.
struct PermissionReminder {
    static let interval: TimeInterval = 24 * 60 * 60

    let file: URL
    private var lastReminded: Date?

    init(file: URL) {
        self.file = file
        lastReminded = (try? String(contentsOf: file, encoding: .utf8)).flatMap {
            try? Date($0.trimmingCharacters(in: .whitespacesAndNewlines), strategy: .iso8601)
        }
    }

    /// Says whether to remind now that a screenshot found the grant missing, remembering the time when it does.
    mutating func remindNow(at now: Date) -> Bool {
        if let lastReminded, now >= lastReminded, now.timeIntervalSince(lastReminded) < Self.interval { return false }
        lastReminded = now
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? Data((now.formatted(.iso8601) + "\n").utf8).write(to: file, options: .atomic)
        return true
    }

    /// Forgets the last reminder once a screenshot shows the grant is held, so a later loss reminds at once.
    mutating func grantSeen() {
        guard lastReminded != nil else { return }
        lastReminded = nil
        try? FileManager.default.removeItem(at: file)
    }
}
