import AppKit
import Foundation
import UserNotifications

/// A notification to post: its title, its body, and the links a click tries in turn until one opens.
public struct UserNotification: Equatable, Sendable {
    public let title: String
    public let body: String
    public let opens: [URL]
}

/// What asking to post a notification came to: posted, waiting on the user to allow notifications, no answer within the seconds given, or not possible and why.
public enum NotificationPosting: Equatable, Sendable {
    case posted
    case awaitingPermission
    case timedOut(TimeInterval)
    case unavailable(String)
}

/// Tries each link in turn and returns the one that opened, or nil if none did.
@discardableResult
func openFirst(_ links: [URL], using open: (URL) -> Bool) -> URL? {
    links.first(where: open)
}

/// Posts through the notification centre and opens a clicked notification's links, when the agent runs from its app bundle.
final class LiveNotifications: NSObject, UNUserNotificationCenterDelegate, @unchecked Sendable {
    private static let opensKey = "opens"

    private static var inAppBundle: Bool { Bundle.main.bundleIdentifier != nil }

    override init() {
        super.init()
        if Self.inAppBundle { UNUserNotificationCenter.current().delegate = self }
    }

    /// Posts the notification, asking the user first to allow notifications if they never answered, and waits up to the timeout for the centre.
    func post(_ notification: UserNotification, timeout: TimeInterval) -> NotificationPosting {
        guard Self.inAppBundle else { return .unavailable("the agent is not running from its app bundle") }
        let answer = Answer()
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            switch settings.authorizationStatus {
            case .notDetermined:
                answer.finish(.awaitingPermission)
                UNUserNotificationCenter.current().requestAuthorization(options: [.alert]) { granted, _ in
                    if granted { Self.add(notification) { _ in } }
                }
            case .denied:
                answer.finish(.unavailable("notifications are turned off for the agent"))
            default:
                Self.add(notification) { error in answer.finish(error.map { .unavailable($0.localizedDescription) } ?? .posted) }
            }
        }
        return answer.wait(timeout: timeout) ?? .timedOut(timeout)
    }

    private static func add(_ notification: UserNotification, done: @escaping @Sendable ((any Error)?) -> Void) {
        let content = UNMutableNotificationContent()
        content.title = notification.title
        content.body = notification.body
        content.userInfo = userInfo(for: notification)
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "screen-recording", content: content, trigger: nil), withCompletionHandler: done
        )
    }

    static func userInfo(for notification: UserNotification) -> [AnyHashable: Any] {
        [opensKey: notification.opens.map(\.absoluteString)]
    }

    /// Opens the first link of a clicked notification that opens, returning it.
    @discardableResult
    static func openLinks(in userInfo: [AnyHashable: Any], using open: (URL) -> Bool) -> URL? {
        openFirst((userInfo[opensKey] as? [String] ?? []).compactMap(URL.init(string:)), using: open)
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler done: @escaping () -> Void
    ) {
        Self.openLinks(in: response.notification.request.content.userInfo, using: NSWorkspace.shared.open)
        done()
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        done([.banner, .list])
    }
}

private final class Answer: @unchecked Sendable {
    private let lock = NSLock()
    private let done = DispatchSemaphore(value: 0)
    private var posting: NotificationPosting?

    func finish(_ posting: NotificationPosting) {
        lock.withLock { self.posting = self.posting ?? posting }
        done.signal()
    }

    func wait(timeout: TimeInterval) -> NotificationPosting? {
        guard done.wait(timeout: .now() + timeout) == .success else { return nil }
        return lock.withLock { posting }
    }
}
