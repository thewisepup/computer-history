import Foundation
@testable import CaptureAgent

func utc(_ iso: String) -> Date {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: iso)!
}

func fixtureID(_ n: Int) -> UUID {
    UUID(uuidString: "6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e0\(n)")!
}

let fixtureRecords: [SpoolRecord] = [
    .capture(
        id: fixtureID(1), at: utc("2026-11-18T09:00:00.000Z"), trigger: .app, appName: "Cursor",
        bundleID: "com.todesktop.230313mzl4w4u92", windowTitle: "spool.py — computer-history",
        text: "def finish(path):\n\treturn \"done\"  # ✓ naïve", fullTextBytes: 46, timedOut: false
    ),
    .capture(
        id: fixtureID(2), at: utc("2026-11-18T09:00:05.250Z"), trigger: .window, appName: "Google Chrome",
        bundleID: "com.google.Chrome", windowTitle: "Pull requests · thewisepup/computer-history",
        text: "Pull requests\nhttps://github.com/thewisepup/computer-history/pulls", fullTextBytes: 73911,
        timedOut: false
    ),
    .capture(
        id: fixtureID(3), at: utc("2026-11-18T09:00:31.007Z"), trigger: .title, appName: "Notion",
        bundleID: "notion.id", windowTitle: "M2 plan", text: "M2 plan\nShip the spool writer",
        fullTextBytes: 29, timedOut: true
    ),
    .capture(
        id: fixtureID(4), at: utc("2026-11-18T09:01:01.500Z"), trigger: .heartbeat, appName: "Spotify",
        bundleID: "com.spotify.client", windowTitle: "Spotify Premium", text: "", fullTextBytes: 0,
        timedOut: false
    ),
    .excluded(
        id: fixtureID(5), at: utc("2026-11-18T09:02:10.000Z"), trigger: .app, appName: "1Password",
        bundleID: "com.1password.1password"
    ),
    .paused(id: fixtureID(6), at: utc("2026-11-18T09:03:00.000Z")),
    .resumed(id: fixtureID(7), at: utc("2026-11-18T09:15:42.999Z")),
]

func captureRecord(text: String, fullTextBytes: Int, timedOut: Bool = false) -> SpoolRecord {
    .capture(
        at: utc("2026-11-18T09:00:00.000Z"), trigger: .app, appName: "Notes", bundleID: nil,
        windowTitle: nil, text: text, fullTextBytes: fullTextBytes, timedOut: timedOut
    )
}

func fixtureLines() throws -> [String] {
    let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().appendingPathComponent("fixtures/spool/records.jsonl")
    return try String(contentsOf: url, encoding: .utf8).split(separator: "\n").map(String.init)
}

final class TestClock: @unchecked Sendable {
    private let lock = NSLock()
    private var current: Date

    init(_ iso: String) { current = utc(iso) }

    var now: Date { lock.withLock { current } }
    func set(_ iso: String) { lock.withLock { current = utc(iso) } }
}

final class TempSpool {
    let directory = FileManager.default.temporaryDirectory
        .appendingPathComponent("spool-tests-\(UUID().uuidString)", isDirectory: true)
    let clock = TestClock("2026-11-18T09:00:00.000Z")

    deinit { try? FileManager.default.removeItem(at: directory) }

    func writer() -> SpoolWriter {
        let clock = clock
        return SpoolWriter(directory: directory, now: { clock.now })
    }

    func names() throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted()
    }

    func finishedNames() throws -> [String] {
        try names().filter { $0.hasSuffix(SpoolWriter.finishedSuffix) }
    }

    func lines(_ name: String) throws -> [String] {
        let contents = try String(contentsOf: directory.appendingPathComponent(name), encoding: .utf8)
        return contents.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    }

    func mode(_ name: String?) throws -> Int {
        let path = name.map { directory.appendingPathComponent($0).path } ?? directory.path
        let attributes = try FileManager.default.attributesOfItem(atPath: path)
        return (attributes[.posixPermissions] as! NSNumber).intValue & 0o777
    }

    func writeOpenFile(_ contents: String) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data(contents.utf8).write(to: directory.appendingPathComponent(SpoolWriter.openFileName))
    }
}

func line(_ record: SpoolRecord) throws -> String {
    String(decoding: try record.jsonLine(), as: UTF8.self)
}
