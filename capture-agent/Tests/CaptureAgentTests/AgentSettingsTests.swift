import Foundation
import Testing
@testable import CaptureAgent

final class TempFolder {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("settings-tests-\(UUID().uuidString)", isDirectory: true)

    init() {
        try! FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    deinit { try? FileManager.default.removeItem(at: url) }

    var environment: [String: String] {
        ["COMPUTER_HISTORY_DB": url.appendingPathComponent("history.db").path]
    }

    func settings(config: String? = nil) throws -> AgentSettings {
        if let config {
            try Data(config.utf8).write(to: url.appendingPathComponent(AgentSettings.configFileName))
        }
        return AgentSettings.load(environment: environment)
    }
}

@Test func theDefaultFolderIsApplicationSupportWithTheSpoolInside() {
    let home = URL(fileURLWithPath: "/Users/someone", isDirectory: true)
    let settings = AgentSettings.load(environment: [:], home: home)
    #expect(settings.folder.path == "/Users/someone/Library/Application Support/ComputerHistory")
    #expect(settings.spoolDirectory.path == "/Users/someone/Library/Application Support/ComputerHistory/spool")
    #expect(settings.configPath.path == "/Users/someone/Library/Application Support/ComputerHistory/agent-config.json")
    #expect(settings.pause.file.path == "/Users/someone/Library/Application Support/ComputerHistory/capture-paused")
}

@Test func overridesFollowTheBackendOrder() {
    let home = URL(fileURLWithPath: "/Users/someone", isDirectory: true)
    let database = AgentSettings.load(environment: ["COMPUTER_HISTORY_DB": "/tmp/ch/test.db"], home: home)
    #expect(database.folder.path == "/tmp/ch")
    #expect(database.spoolDirectory.path == "/tmp/ch/spool")
    let both = AgentSettings.load(
        environment: ["COMPUTER_HISTORY_DB": "/tmp/ch/test.db", "COMPUTER_HISTORY_SPOOL": "/tmp/other-spool"], home: home
    )
    #expect(both.folder.path == "/tmp/ch")
    #expect(both.spoolDirectory.path == "/tmp/other-spool")
    let spoolOnly = AgentSettings.load(environment: ["COMPUTER_HISTORY_SPOOL": "/tmp/other-spool"], home: home)
    #expect(spoolOnly.folder.path == "/Users/someone/Library/Application Support/ComputerHistory")
    #expect(spoolOnly.spoolDirectory.path == "/tmp/other-spool")
}

@Test func emptyOverridesCountAsUnsetAndTildeMeansHome() {
    let home = URL(fileURLWithPath: "/Users/someone", isDirectory: true)
    let empty = AgentSettings.load(environment: ["COMPUTER_HISTORY_DB": "", "COMPUTER_HISTORY_SPOOL": ""], home: home)
    #expect(empty.folder.path == "/Users/someone/Library/Application Support/ComputerHistory")
    #expect(empty.spoolDirectory.path == "/Users/someone/Library/Application Support/ComputerHistory/spool")
    let tilde = AgentSettings.load(
        environment: ["HOME": "/Users/other", "COMPUTER_HISTORY_DB": "~/ch/test.db", "COMPUTER_HISTORY_SPOOL": "~/spool"],
        home: home
    )
    #expect(tilde.folder.path == "/Users/other/ch")
    #expect(tilde.spoolDirectory.path == "/Users/other/spool")
    #expect(AgentSettings.load(environment: ["HOME": "/Users/other"], home: home).folder.path
        == "/Users/other/Library/Application Support/ComputerHistory")
}

@Test func runAndTheControlCommandsUseTheAccountFolderWhateverTheEnvironmentSays() throws {
    let account = TempFolder()
    let elsewhere = TempFolder()
    let real = AgentSettings.defaultFolder(home: account.url)
    try FileManager.default.createDirectory(at: real, withIntermediateDirectories: true)
    try Data(#"{"idle_threshold_seconds": 60}"#.utf8).write(to: real.appendingPathComponent(AgentSettings.configFileName))
    try Data(#"{"text_cap_bytes": 10000000}"#.utf8).write(to: elsewhere.url.appendingPathComponent(AgentSettings.configFileName))
    let environment = [
        "HOME": elsewhere.url.path,
        "COMPUTER_HISTORY_DB": elsewhere.url.appendingPathComponent("history.db").path,
        "COMPUTER_HISTORY_SPOOL": elsewhere.url.appendingPathComponent("spool").path,
    ]
    for command in [AgentCommand.run, .status, .pause, .resume] {
        let settings = AgentSettings.load(for: command, environment: environment, accountHome: account.url)
        #expect(settings.folder == real)
        #expect(settings.spoolDirectory == real.appendingPathComponent("spool", isDirectory: true))
        #expect(settings.pause.file == real.appendingPathComponent(AgentSettings.pauseFileName))
        #expect(settings.capture.idleThreshold == 60)
        #expect(settings.windowText.textCapBytes == WindowTextSettings().textCapBytes)
    }
    for command in [AgentCommand.checkConfig, .scriptedSession(script: "day.json")] {
        let settings = AgentSettings.load(for: command, environment: environment, accountHome: account.url)
        #expect(settings.folder.path == elsewhere.url.path)
        #expect(settings.spoolDirectory.path == elsewhere.url.appendingPathComponent("spool").path)
        #expect(settings.windowText.textCapBytes == 10_000_000)
    }
}

@Test func theInstanceLockSitsInTheAccountFolder() {
    let home = URL(fileURLWithPath: "/Users/someone", isDirectory: true)
    #expect(InstanceLock(accountHome: home).file == AgentSettings.defaultFolder(home: home).appendingPathComponent("agent-instance.lock"))
}

@Test func theAccountHomeComesFromTheUserDatabase() throws {
    let entry = try #require(getpwuid(getuid()))
    #expect(accountHome()?.path == String(cString: entry.pointee.pw_dir))
}

@Test func aMissingFileMeansDefaults() throws {
    let settings = try TempFolder().settings()
    #expect(settings.configFile == .missing)
    #expect(settings.problems.isEmpty)
    #expect(settings.capture == CaptureSettings())
    #expect(settings.windowText == WindowTextSettings())
    #expect(settings.denylist == Denylist())
    #expect(settings.screenshots == ScreenshotSettings(enabled: true, longEdge: 1440, quality: 60, changePixels: 6, keepAfter: 600))
    #expect(Denylist.builtIn == [
        "com.1password.1password", "com.agilebits.onepassword7", "com.apple.keychainaccess", "com.apple.Passwords",
    ])
    #expect(settings.report == ["config not found at \(settings.configPath.path), using defaults, \(Denylist.builtIn.count) apps denylisted"])
}

@Test func readsEveryKey() throws {
    let settings = try TempFolder().settings(config: """
        {
          "denylist": ["com.apple.calculator"],
          "accessibility_flag_off_list": ["com.google.Chrome"],
          "idle_threshold_seconds": 300,
          "capture_heartbeat_seconds": 60,
          "text_cap_bytes": 20000,
          "call_timeout_seconds": 0.5,
          "window_timeout_seconds": 3,
          "screenshots": false,
          "screenshot_long_edge_pixels": 1024,
          "screenshot_jpeg_quality": 80,
          "screenshot_change_pixels": 20,
          "screenshot_keep_after_minutes": 30
        }
        """)
    #expect(settings.configFile == .read)
    #expect(settings.problems.isEmpty)
    #expect(settings.capture == CaptureSettings(idleThreshold: 300, heartbeatInterval: 60))
    #expect(settings.windowText == WindowTextSettings(
        textCapBytes: 20_000, callTimeout: 0.5, windowTimeout: 3, flagOffList: ["com.google.Chrome"]
    ))
    #expect(settings.denylist == Denylist(adding: ["com.apple.calculator"]))
    #expect(settings.screenshots == ScreenshotSettings(enabled: false, longEdge: 1024, quality: 80, changePixels: 20, keepAfter: 1800))
}

@Test func aUserDenylistExtendsTheDefaultsAndCannotRemoveThem() throws {
    let settings = try TempFolder().settings(config: #"{"denylist": []}"#)
    #expect(settings.problems.isEmpty)
    #expect(settings.denylist == Denylist())
}

@Test(arguments: [
    ("{", "the file is not a JSON object"),
    ("[1, 2]", "the file is not a JSON object"),
    ("", "the file is not a JSON object"),
])
func anInvalidFileIsReportedAndDefaultsAreUsed(config: String, problem: String) throws {
    let settings = try TempFolder().settings(config: config)
    #expect(settings.configFile == .unreadable)
    #expect(settings.problems == [problem])
    #expect(settings.capture == CaptureSettings())
    #expect(settings.windowText == WindowTextSettings())
    #expect(settings.denylist == Denylist())
    #expect(settings.report.first == "config at \(settings.configPath.path) could not be used, using defaults, \(Denylist.builtIn.count) apps denylisted")
}

@Test func anUnreadableFileIsReported() throws {
    let folder = TempFolder()
    try FileManager.default.createDirectory(
        at: folder.url.appendingPathComponent(AgentSettings.configFileName), withIntermediateDirectories: true
    )
    let settings = AgentSettings.load(environment: folder.environment)
    #expect(settings.configFile == .unreadable)
    #expect(settings.problems.count == 1)
    #expect(settings.problems[0].hasPrefix("cannot read the file"))
    #expect(settings.denylist == Denylist())
}

@Test func unknownKeysAreReportedAndTheRestIsStillRead() throws {
    let settings = try TempFolder().settings(config: #"{"idle_threshold_seconds": 60, "idle": 5, "Denylist": ["x"]}"#)
    #expect(settings.problems == [#"unknown key "Denylist" ignored"#, #"unknown key "idle" ignored"#])
    #expect(settings.capture.idleThreshold == 60)
    #expect(settings.denylist == Denylist())
}

@Test func theWatchdogSectionIsLeftToTheBackend() throws {
    let settings = try TempFolder().settings(config: #"{"watchdog": {"capture_agent_minutes": 10, "oops": 1}, "idle_threshold_seconds": 60}"#)
    #expect(settings.problems.isEmpty)
    #expect(settings.capture.idleThreshold == 60)
}

@Test(arguments: [
    (#"{"idle_threshold_seconds": 5}"#, "idle_threshold_seconds 5 is outside 10–86400, using 180"),
    (#"{"idle_threshold_seconds": "300"}"#, "idle_threshold_seconds must be a number of seconds, using 180"),
    (#"{"idle_threshold_seconds": true}"#, "idle_threshold_seconds must be a number of seconds, using 180"),
    (#"{"idle_threshold_seconds": null}"#, "idle_threshold_seconds must be a number of seconds, using 180"),
    (#"{"capture_heartbeat_seconds": 1}"#, "capture_heartbeat_seconds 1 is outside 5–60, using 30"),
    (#"{"capture_heartbeat_seconds": 61}"#, "capture_heartbeat_seconds 61 is outside 5–60, using 30"),
    (#"{"text_cap_bytes": 100}"#, "text_cap_bytes 100 is outside 1000–10000000, using 50000"),
    (#"{"text_cap_bytes": 2000.5}"#, "text_cap_bytes must be a whole number, using 50000"),
    (#"{"text_cap_bytes": 1e300}"#, "text_cap_bytes must be a whole number, using 50000"),
    (#"{"call_timeout_seconds": 0}"#, "call_timeout_seconds 0 is outside 0.05–5, using 0.25"),
    (#"{"window_timeout_seconds": -1}"#, "window_timeout_seconds -1 is outside 0.1–60, using 2"),
    (#"{"accessibility_flag_off_list": "com.google.Chrome"}"#, "accessibility_flag_off_list must be a list of bundle ids, ignored"),
    (#"{"screenshots": 0}"#, "screenshots must be true or false, using true"),
    (#"{"screenshots": "off"}"#, "screenshots must be true or false, using true"),
    (#"{"screenshot_long_edge_pixels": 100}"#, "screenshot_long_edge_pixels 100 is outside 256–8192, using 1440"),
    (#"{"screenshot_long_edge_pixels": 1440.5}"#, "screenshot_long_edge_pixels must be a whole number, using 1440"),
    (#"{"screenshot_jpeg_quality": 0}"#, "screenshot_jpeg_quality 0 is outside 1–100, using 60"),
    (#"{"screenshot_jpeg_quality": 101}"#, "screenshot_jpeg_quality 101 is outside 1–100, using 60"),
    (#"{"screenshot_change_pixels": -1}"#, "screenshot_change_pixels -1 is outside 0–1000, using 6"),
    (#"{"screenshot_change_pixels": 1001}"#, "screenshot_change_pixels 1001 is outside 0–1000, using 6"),
    (#"{"screenshot_change_pixels": 7.5}"#, "screenshot_change_pixels must be a whole number, using 6"),
    (#"{"screenshot_change_percent": 0.05}"#, "unknown key \"screenshot_change_percent\" ignored"),
    (#"{"screenshot_keep_after_minutes": 0}"#, "screenshot_keep_after_minutes 0 is outside 1–1440, using 10"),
    (#"{"screenshot_keep_after_minutes": 2.5}"#, "screenshot_keep_after_minutes must be a whole number, using 10"),
    (#"{"screenshot_duplicate_threshold_bits": 2}"#, "unknown key \"screenshot_duplicate_threshold_bits\" ignored"),
])
func anOutOfRangeOrWrongTypeValueFallsBackToItsDefault(config: String, problem: String) throws {
    let settings = try TempFolder().settings(config: config)
    #expect(settings.configFile == .read)
    #expect(settings.problems == [problem])
    #expect(settings.capture == CaptureSettings())
    #expect(settings.windowText == WindowTextSettings())
    #expect(settings.screenshots == ScreenshotSettings())
}

@Test func aBadDenylistKeepsTheDefaultsAndEveryUsableEntry() throws {
    let wrongType = try TempFolder().settings(config: #"{"denylist": "com.apple.calculator"}"#)
    #expect(wrongType.problems == ["denylist must be a list of bundle ids, ignored"])
    #expect(wrongType.denylist == Denylist())
    let badEntries = try TempFolder().settings(config: #"{"denylist": ["com.apple.calculator", 7, "", null]}"#)
    #expect(badEntries.problems == [
        "denylist entry 2 is not a bundle id, ignored",
        "denylist entry 3 is not a bundle id, ignored",
        "denylist entry 4 is not a bundle id, ignored",
    ])
    #expect(badEntries.denylist == Denylist(adding: ["com.apple.calculator"]))
}

@Test func checkConfigPrintsTheSettingsAndFailsOnProblems() throws {
    let good = checkConfig(try TempFolder().settings())
    #expect(good.exitCode == 0)
    #expect(good.message.contains("denylist, built-in plus config: com.1password.1password, com.agilebits.onepassword7, com.apple.keychainaccess, com.apple.passwords"))
    #expect(good.message.contains("idle threshold: 180s"))
    #expect(good.message.contains(
        "screenshots: on, long edge 1440 px, JPEG quality 60, duplicate when under 6 thumbnail pixels (9x9 points each) changed, "
            + "a new kept image after 10 min"
    ))
    let bad = checkConfig(try TempFolder().settings(config: #"{"oops": 1}"#))
    #expect(bad.exitCode == 1)
    #expect(bad.message.contains(#"config problem: unknown key "oops" ignored"#))
}
