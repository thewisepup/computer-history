import CoreGraphics
import Foundation

/// The Screen Recording pane of System Settings: the links that open it, newest form first, and the reminder that opens it when clicked.
public enum ScreenRecordingSettings {
    public static let links = [
        URL(string: "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture")!,
        URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!,
    ]

    static let reminder = UserNotification(
        title: "Computer History can't take screenshots",
        body: "Screen Recording permission is missing. Click to open the setting and turn on Computer History Agent.",
        opens: links
    )

    /// Tries each link in turn and returns the one that opened, or nil if none did.
    @discardableResult
    public static func open(using open: (URL) -> Bool) -> URL? {
        links.first(where: open)
    }
}

/// Asks macOS for the Screen Recording grant, then opens its settings pane, for the install script.
public func requestScreenRecording(
    request: () -> Bool = CGRequestScreenCaptureAccess, open: (URL) -> Bool
) -> CommandOutcome {
    let asked = request()
        ? "macOS reports Screen Recording granted."
        : "Asked macOS for Screen Recording permission."
    guard let opened = ScreenRecordingSettings.open(using: open) else {
        return CommandOutcome(exitCode: 1, message: "\(asked) Could not open the Screen Recording settings.")
    }
    return CommandOutcome(
        exitCode: 0,
        message: "\(asked) Opened \(opened.absoluteString): turn on Computer History Agent there if it is off."
    )
}
