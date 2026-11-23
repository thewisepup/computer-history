import Foundation

/// The agent's folder, its spool, and the settings read from its config file, with any problems found in that file.
public struct AgentSettings: Equatable, Sendable {
    public static let databaseEnvironmentVariable = "COMPUTER_HISTORY_DB"
    public static let spoolEnvironmentVariable = "COMPUTER_HISTORY_SPOOL"
    public static let configFileName = "agent-config.json"
    public static let pauseFileName = "capture-paused"
    public static let permissionReminderFileName = "screen-recording-reminded"

    public enum ConfigFile: Equatable, Sendable {
        case missing, read, unreadable
    }

    public var folder: URL
    public var spoolDirectory: URL
    public var capture = CaptureSettings()
    public var windowText = WindowTextSettings()
    public var denylist = Denylist()
    public var screenshots = ScreenshotSettings()
    public var configFile: ConfigFile = .missing
    public var problems: [String] = []

    public var configPath: URL { folder.appendingPathComponent(Self.configFileName) }
    public var pause: PauseSwitch { PauseSwitch(file: folder.appendingPathComponent(Self.pauseFileName)) }
    public var permissionReminderFile: URL { folder.appendingPathComponent(Self.permissionReminderFileName) }

    /// Finds the folder the way the backend does, then reads the config file in it, falling back to defaults for anything missing or invalid.
    public static func load(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        home: URL = FileManager.default.homeDirectoryForCurrentUser
    ) -> AgentSettings {
        let home = environment["HOME"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0, isDirectory: true) } ?? home
        let folder = nonEmpty(environment[databaseEnvironmentVariable])
            .map { expandingTilde($0, home: home).deletingLastPathComponent() } ?? defaultFolder(home: home)
        let spool = nonEmpty(environment[spoolEnvironmentVariable]).map { expandingTilde($0, home: home) }
            ?? folder.appendingPathComponent("spool", isDirectory: true)
        var settings = AgentSettings(folder: folder, spoolDirectory: spool)
        settings.readConfigFile()
        return settings
    }

    /// Reads the config file in the account's real folder, ignoring HOME and the folder and spool overrides.
    public static func fixed(accountHome: URL) -> AgentSettings {
        let folder = defaultFolder(home: accountHome)
        var settings = AgentSettings(folder: folder, spoolDirectory: folder.appendingPathComponent("spool", isDirectory: true))
        settings.readConfigFile()
        return settings
    }

    /// The settings a command runs with: check-config and scripted-session follow the environment, every other command uses the account's real folder.
    public static func load(
        for command: AgentCommand,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        accountHome: URL
    ) -> AgentSettings {
        switch command {
        case .checkConfig, .scriptedSession: load(environment: environment, home: accountHome)
        case .run, .install, .uninstall, .status, .pause, .resume, .requestScreenRecording, .usage: fixed(accountHome: accountHome)
        }
    }

    static func defaultFolder(home: URL) -> URL {
        home.appendingPathComponent("Library/Application Support/ComputerHistory", isDirectory: true)
    }

    /// The lines the agent logs at start about where its settings came from.
    public var report: [String] {
        let source = switch configFile {
        case .missing: "config not found at \(configPath.path), using defaults"
        case .read: "config read from \(configPath.path)"
        case .unreadable: "config at \(configPath.path) could not be used, using defaults"
        }
        return ["\(source), \(denylist.bundleIDs.count) apps denylisted"] + problems.map { "config problem: \($0)" }
    }

    private mutating func readConfigFile() {
        guard FileManager.default.fileExists(atPath: configPath.path) else { return }
        let data: Data
        do {
            data = try Data(contentsOf: configPath)
        } catch {
            configFile = .unreadable
            problems.append("cannot read the file (\(error.localizedDescription))")
            return
        }
        guard let object = try? JSONSerialization.jsonObject(with: data), let config = object as? [String: Any] else {
            configFile = .unreadable
            problems.append("the file is not a JSON object")
            return
        }
        configFile = .read
        apply(config)
    }

    private mutating func apply(_ config: [String: Any]) {
        for name in config.keys.sorted() where ConfigKey(rawValue: name) == nil {
            problems.append("unknown key \"\(name)\" ignored")
        }
        for key in ConfigKey.allCases {
            guard let value = config[key.rawValue] else { continue }
            switch key {
            case .denylist:
                denylist = Denylist(adding: bundleIDs(value, key: key))
            case .accessibilityFlagOffList:
                windowText.flagOffList = Set(bundleIDs(value, key: key))
            case .idleThresholdSeconds:
                capture.idleThreshold = seconds(value, key: key, range: 10...86_400, default: capture.idleThreshold)
            case .captureHeartbeatSeconds:
                capture.heartbeatInterval = seconds(value, key: key, range: 5...60, default: capture.heartbeatInterval)
            case .callTimeoutSeconds:
                windowText.callTimeout = seconds(value, key: key, range: 0.05...5, default: windowText.callTimeout)
            case .windowTimeoutSeconds:
                windowText.windowTimeout = seconds(value, key: key, range: 0.1...60, default: windowText.windowTimeout)
            case .textCapBytes:
                windowText.textCapBytes = wholeNumber(value, key: key, range: 1_000...10_000_000, default: windowText.textCapBytes)
            case .screenshots:
                screenshots.enabled = flag(value, key: key, default: screenshots.enabled)
            case .screenshotLongEdgePixels:
                screenshots.longEdge = wholeNumber(value, key: key, range: 256...8_192, default: screenshots.longEdge)
            case .screenshotJPEGQuality:
                screenshots.quality = wholeNumber(value, key: key, range: 1...100, default: screenshots.quality)
            case .screenshotChangePixels:
                screenshots.changePixels = wholeNumber(value, key: key, range: 0...1_000, default: screenshots.changePixels)
            case .screenshotKeepAfterMinutes:
                screenshots.keepAfter = TimeInterval(
                    wholeNumber(value, key: key, range: 1...1_440, default: Int(screenshots.keepAfter / 60)) * 60
                )
            case .watchdog:
                break
            }
        }
    }

    private mutating func bundleIDs(_ value: Any, key: ConfigKey) -> [String] {
        guard let list = value as? [Any] else {
            problems.append("\(key.rawValue) must be a list of bundle ids, ignored")
            return []
        }
        var ids: [String] = []
        for (index, entry) in list.enumerated() {
            if let id = entry as? String, !id.isEmpty {
                ids.append(id)
            } else {
                problems.append("\(key.rawValue) entry \(index + 1) is not a bundle id, ignored")
            }
        }
        return ids
    }

    private mutating func seconds(
        _ value: Any, key: ConfigKey, range: ClosedRange<Double>, default fallback: TimeInterval
    ) -> TimeInterval {
        guard let number = number(value) else {
            problems.append("\(key.rawValue) must be a number of seconds, using \(formatted(fallback))")
            return fallback
        }
        guard range.contains(number) else {
            problems.append(
                "\(key.rawValue) \(formatted(number)) is outside \(formatted(range.lowerBound))–\(formatted(range.upperBound)), using \(formatted(fallback))"
            )
            return fallback
        }
        return number
    }

    private mutating func flag(_ value: Any, key: ConfigKey, default fallback: Bool) -> Bool {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else {
            problems.append("\(key.rawValue) must be true or false, using \(fallback)")
            return fallback
        }
        return number.boolValue
    }

    private mutating func wholeNumber(_ value: Any, key: ConfigKey, range: ClosedRange<Int>, default fallback: Int) -> Int {
        guard let number = number(value), number.rounded() == number, abs(number) < 1e15 else {
            problems.append("\(key.rawValue) must be a whole number, using \(fallback)")
            return fallback
        }
        guard range.contains(Int(number)) else {
            problems.append("\(key.rawValue) \(Int(number)) is outside \(range.lowerBound)–\(range.upperBound), using \(fallback)")
            return fallback
        }
        return Int(number)
    }
}

private enum ConfigKey: String, CaseIterable {
    case denylist
    case accessibilityFlagOffList = "accessibility_flag_off_list"
    case idleThresholdSeconds = "idle_threshold_seconds"
    case captureHeartbeatSeconds = "capture_heartbeat_seconds"
    case textCapBytes = "text_cap_bytes"
    case callTimeoutSeconds = "call_timeout_seconds"
    case windowTimeoutSeconds = "window_timeout_seconds"
    case screenshots
    case screenshotLongEdgePixels = "screenshot_long_edge_pixels"
    case screenshotJPEGQuality = "screenshot_jpeg_quality"
    case screenshotChangePixels = "screenshot_change_pixels"
    case screenshotKeepAfterMinutes = "screenshot_keep_after_minutes"
    /// Read and checked by the backend's watchdog, not by the agent.
    case watchdog
}

/// Prints where the settings came from, every problem in the config file, and the settings in effect.
public func checkConfig(_ settings: AgentSettings) -> CommandOutcome {
    var lines = settings.report
    lines += [
        "folder: \(settings.folder.path)",
        "spool: \(settings.spoolDirectory.path)",
        "denylist, built-in plus config: \(settings.denylist.bundleIDs.sorted().joined(separator: ", "))",
        "accessibility flag off-list: \(settings.windowText.flagOffList.sorted().joined(separator: ", "))",
        "idle threshold: \(formatted(settings.capture.idleThreshold))s",
        "capture heartbeat: \(formatted(settings.capture.heartbeatInterval))s",
        "text cap: \(settings.windowText.textCapBytes) bytes",
        "call timeout: \(formatted(settings.windowText.callTimeout))s",
        "window timeout: \(formatted(settings.windowText.windowTimeout))s",
        "screenshots: \(settings.screenshots.enabled ? "on" : "off"), long edge \(settings.screenshots.longEdge) px, "
            + "JPEG quality \(settings.screenshots.quality), duplicate when under \(settings.screenshots.changePixels) "
            + "thumbnail pixels (9x9 points each) changed, a new kept image after \(formatted(settings.screenshots.keepAfter / 60)) min",
    ]
    return CommandOutcome(exitCode: settings.problems.isEmpty ? 0 : 1, message: lines.joined(separator: "\n"))
}

private func number(_ value: Any) -> Double? {
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
    return number.doubleValue
}

private func formatted(_ value: Double) -> String {
    value.rounded() == value && abs(value) < 1e15 ? String(Int(value)) : String(value)
}

private func nonEmpty(_ value: String?) -> String? {
    value?.isEmpty == false ? value : nil
}

private func expandingTilde(_ path: String, home: URL) -> URL {
    if path == "~" { return home }
    if path.hasPrefix("~/") { return home.appendingPathComponent(String(path.dropFirst(2))) }
    return URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
}
