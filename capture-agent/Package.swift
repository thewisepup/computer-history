// swift-tools-version:6.0
import PackageDescription

/// The capture agent macOS starts at login, which writes captures to the spool for the backend.
///
///     computer-history-agent/main.swift   load the settings, parse the command line, pick LiveMac, run
///           |
///     AgentSettings.swift   the folder, spool and settings from the environment and agent-config.json
///     AgentCommand.swift    the commands the binary accepts, and the message and exit code each ends with
///     LoginItem.swift       install, uninstall and status through SMAppService, with the pause state
///     PauseSwitch.swift     the capture-paused file the pause and resume commands set
///     AgentIdentity.swift   bundle id and names shared by binary, bundle and login item
///     AgentLifecycle.swift  on start: exit if another agent holds the spool, else Accessibility check,
///           |               spool recovery, capture thread; then the minute log line and spool finish
///     CaptureLoop.swift     the capture thread: each tick asks the decision what to do, then reads
///           |               the window or writes a capture, excluded, paused or resumed record,
///           |               and after each capture queues its screenshot record
///     CaptureScreenshot.swift   the screenshot stage: password-field check, picture, duplicate
///           |                   check, image saved, and the screenshot record that names the capture;
///           |                   a missing grant posts the reminder, a picture taken clears it
///     PermissionReminder.swift  the once-a-day missing-grant reminder: when to post, what to log,
///           |                   the last posted time kept in screen-recording-reminded
///     ScreenRecordingSettings.swift   the settings pane's links, the reminder that opens them, and
///           |                         the request-screen-recording command install.sh runs
///     RecognitionQueue.swift    the recognition thread: writes screenshot records in capture order,
///           |                   reading the text of each kept image, duplicates copying it
///     TextRecognition.swift     the text in a saved picture, read by Vision
///     FrameDedup.swift      the last kept screenshot of each of the most recently seen windows,
///           |               and whether a new one changed enough or is old enough to keep
///     FrameThumbnail.swift  the small grey copy of a screenshot that dedup compares, pixel by pixel
///     CaptureDecision.swift what a tick does: paused, silent, excluded, capture due or nothing,
///           |               and whether the focused app's window may be touched
///     Denylist.swift        the apps never read: the built-in password managers plus the config's
///     CaptureSchedule.swift capture timing: settle delay, minimum gap, heartbeat, silence gating
///     CaptureCounts.swift   captures written, excluded, timed out and cut off, for the minute log line
///     AppAndWindowWatch.swift   focus changes: the app from the focused app alone, the window and
///                               title by polling that app's accessibility tree
///     Presence.swift        idle seconds, screen lock, sleep and wake; the reasons for silence
///     FocusedApplication.swift   the focused app, asked of the system-wide accessibility element
///     WindowTextReader.swift     reads the focused window's title and text
///     WindowWalk.swift      the tree walk: content roles only, each element once, within timeouts
///     CappedText.swift      joins text pieces up to the byte cap, counting the full length past it
///     AccessibilityElement.swift  the accessibility tree behind a protocol, and its live form
///     AccessibilityFlag.swift     which apps get the Chromium and Electron accessibility flags
///     Accessibility.swift   whether this process holds the Accessibility grant
///     SecureField.swift     whether the focused element is a password field, or no answer
///     WindowScreenshot.swift     a ScreenCaptureKit still of the window matching the focused
///                                window's frame, one request at a time, as a WindowImage
///                                that carries the window's id
///     ImageStore.swift      where kept screenshots go: JPEGImageStore downscales, encodes and saves
///                           each in its day's folder
///     FrameHash.swift       the 64-bit difference hash each screenshot record carries
///     Mac.swift             everything the loop asks of the Mac, and LiveMac, which asks macOS
///     Notifications.swift   posting through the notification centre, and opening the first link
///                           of a clicked one that opens
///     ScriptedMac.swift     a Mac on a virtual clock with scripted accessibility elements, fixture images
///                           and scripted recognized text
///     ScriptedSession.swift the scripted-session command: plays a script through the real loop and spool
///           |
///     ScratchFolderCheck.swift   refuses the agent's real folder, or one that holds a database
///     ScriptPlayer.swift    builds the script's apps on a ScriptedMac and applies each step as it comes due
///                           ScriptedRecognition reads each kept picture as its window's scripted text
///     CaptureScript.swift   a scripted session's JSON: apps, windows and timed steps
///     SpoolWriter.swift     append records to open.part; finish it to <stamp>.jsonl
///     SpoolRecord.swift     one record, the hash and cut-off it derives, and its JSON line
///     ScreenshotRecord.swift    a capture's screenshot record: its status, image and recognized text
///     SpoolTime.swift       UTC milliseconds as ISO-8601 and as file name stamps
///
/// The spool and its record format are described in README.md.
let package = Package(
    name: "CaptureAgent",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "computer-history-agent", targets: ["computer-history-agent"]),
    ],
    targets: [
        .target(name: "CaptureAgent"),
        .executableTarget(name: "computer-history-agent", dependencies: ["CaptureAgent"]),
        .testTarget(name: "CaptureAgentTests", dependencies: ["CaptureAgent"], resources: [.copy("Fixtures/recognized-text.jpg")]),
    ]
)
