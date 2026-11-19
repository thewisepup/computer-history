// swift-tools-version:6.0
import PackageDescription

/// The capture agent macOS starts at login, which writes captures to the spool for the backend.
///
///     computer-history-agent/main.swift   load the settings, parse the command line, pick LiveMac, run
///           |
///     AgentSettings.swift   the folder, spool and settings from the environment and agent-config.json
///     AgentCommand.swift    the commands the binary accepts and what each prints
///     LoginItem.swift       install, uninstall and status through SMAppService, with the pause state
///     PauseSwitch.swift     the capture-paused file the pause and resume commands set
///     AgentIdentity.swift   bundle id and names shared by binary, bundle and login item
///     AgentLifecycle.swift       on start: Accessibility check, spool recovery, capture thread; then
///           |               the minute log line and the one-minute spool finish on the main run loop
///     CaptureLoop.swift     the capture thread: each tick asks the decision what to do, then reads
///           |               the window or writes a capture, excluded, paused or resumed record
///     CaptureDecision.swift what a tick does: paused, silent, excluded, capture due or nothing,
///           |               and whether the focused app's window may be touched
///     Denylist.swift        the apps never read: the built-in password managers plus the config's
///     CaptureSchedule.swift capture timing: settle delay, minimum gap, heartbeat, silence gating
///     CaptureCounts.swift   captures written, excluded, timed out and cut off, for the minute log line
///     AppAndWindowWatch.swift app changes from the focused app alone; window and title changes by
///                           polling that app's accessibility tree
///     Presence.swift        idle seconds, screen lock, sleep and wake; the reasons for silence
///     FocusedApplication.swift   the focused app, asked of the system-wide accessibility element
///     WindowTextReader.swift     reads the focused window's title and text
///     WindowWalk.swift      the tree walk: content roles only, each element once, within timeouts
///     CappedText.swift      joins text pieces up to the byte cap, counting the full length past it
///     AccessibilityElement.swift  the accessibility tree behind a protocol, and its live form
///     AccessibilityFlag.swift     which apps get the Chromium and Electron accessibility flags
///     Accessibility.swift   whether this process holds the Accessibility grant
///     Mac.swift             everything the loop asks of the Mac, and LiveMac, which asks macOS
///     ScriptedMac.swift     a Mac on a virtual clock with scripted accessibility elements
///     ScriptedSession.swift the scripted-session command: plays a script through the real loop and spool
///           |
///     ScratchFolderCheck.swift   refuses the agent's real folder, or one that holds a database
///     ScriptPlayer.swift    builds the script's apps on a ScriptedMac and applies each step as it comes due
///     CaptureScript.swift   a scripted session's JSON: apps, windows and timed steps
///     SpoolWriter.swift     append records to open.part; finish it to <stamp>.jsonl
///     SpoolRecord.swift     one record, the hash and cut-off it derives, and its JSON line
///     SpoolTime.swift       UTC milliseconds as ISO-8601 and as file name stamps
///
/// Spool: `~/Library/Application Support/ComputerHistory/spool/` by default. Records are appended to
/// `open.part`, one JSON object per line. Every minute a non-empty `open.part` is renamed to
/// `<yyyyMMdd'T'HHmmss.SSS'Z'>.jsonl` in UTC, and a leftover one is finished the same way on
/// start. A torn last line is dropped before the rename, and a finished file only ever holds whole
/// lines. Each finished name is at least one millisecond after every name this run has used and the
/// newest name in the folder at start, so names sort chronologically and never replace a file. The
/// backend reads only `*.jsonl`. `agent.lock` keeps a second agent from writing to the same spool.
///
/// Every record carries every key, sorted, with null where a key does not apply:
///
///     version          1
///     id               lowercase UUID, the observation's source_id
///     captured_at      UTC ISO-8601 with milliseconds, e.g. 2026-11-18T09:00:05.250Z
///     kind             capture | excluded | paused | resumed
///     trigger          app | window | title | heartbeat; null for paused and resumed
///     app_name         focused app; null for paused and resumed
///     bundle_id        focused app's bundle id, or null
///     window_title     capture only
///     text             capture only: the window's text, possibly cut off or partial
///     text_sha256      capture only: lowercase hex SHA-256 of text as UTF-8
///     full_text_bytes  capture only: UTF-8 length of all text read, before any cut
///     text_cut_off     capture only: true when text is shorter than the full text
///     timed_out        capture only: true when reading stopped at a timeout and the text is partial
///
/// `fixtures/spool/records.jsonl` at the repository root holds one example of every kind and
/// trigger, and the tests check the encoder writes exactly those lines.
let package = Package(
    name: "CaptureAgent",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "computer-history-agent", targets: ["computer-history-agent"]),
    ],
    targets: [
        .target(name: "CaptureAgent"),
        .executableTarget(name: "computer-history-agent", dependencies: ["CaptureAgent"]),
        .testTarget(name: "CaptureAgentTests", dependencies: ["CaptureAgent"]),
    ]
)
