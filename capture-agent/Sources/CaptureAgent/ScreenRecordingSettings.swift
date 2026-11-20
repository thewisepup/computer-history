import CoreGraphics
import Foundation

/// The Screen Recording pane of System Settings: the links that open it, newest form first, and the reminder whose click opens it.
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
}

/// Asks macOS for the Screen Recording grant and, unless macOS reports it held, opens its settings pane, for the install script.
public func requestScreenRecording(
    request: () -> Bool = CGRequestScreenCaptureAccess, open: (URL) -> Bool
) -> CommandOutcome {
    guard !request() else { return CommandOutcome(exitCode: 0, message: "macOS reports Screen Recording granted.") }
    let asked = "Asked macOS for Screen Recording permission."
    guard let opened = openFirst(ScreenRecordingSettings.links, using: open) else {
        return CommandOutcome(exitCode: 1, message: "\(asked) Could not open the Screen Recording settings.")
    }
    return CommandOutcome(exitCode: 0, message: "\(asked) Opened \(opened.absoluteString): turn on Computer History Agent there.")
}
