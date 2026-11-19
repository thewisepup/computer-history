// swift-tools-version:6.0
import PackageDescription

/// The capture agent macOS starts at login, which writes captures to the spool for the backend.
///
///     computer-history-agent/main.swift   parse the command line, build the real I/O, run
///           |
///     AgentCommand.swift    the commands the binary accepts and what each prints
///     LoginItem.swift       install, uninstall and status through SMAppService
///     AgentIdentity.swift   bundle id and names shared by binary, bundle and login item
///     AgentLoop.swift       on start: Accessibility check, spool recovery; then the
///           |               heartbeat and the one-minute spool finish on the run loop
///     Accessibility.swift   whether this process holds the Accessibility grant
///     SpoolWriter.swift     append records to open.part; finish it to <stamp>.jsonl
///     SpoolRecord.swift     one record and its JSON line
///     SpoolTime.swift       UTC milliseconds as ISO-8601 and as file name stamps
///
/// Spool: `~/Library/Application Support/ComputerHistory/spool/`. Records are appended to
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
