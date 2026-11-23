import CryptoKit
import Foundation

/// One line of the spool: a capture of the focused window, or a labelled gap or moment with no text.
public struct SpoolRecord: Equatable, Sendable {
    public static let formatVersion = 1

    public enum Kind: String, CaseIterable, Sendable {
        case capture, excluded, paused, resumed, slept, woke
    }

    public enum Trigger: String, CaseIterable, Sendable {
        case app, window, title, heartbeat
    }

    public let id: UUID
    public let capturedAt: Date
    public let kind: Kind
    public let trigger: Trigger?
    public let appName: String?
    public let bundleID: String?
    public let windowTitle: String?
    public let text: String?
    public let fullTextBytes: Int?
    public let timedOut: Bool?

    /// The lowercase hex SHA-256 of the text as UTF-8, for records that carry text.
    public var textSHA256: String? { text.map(sha256Hex) }

    /// Whether the text is shorter than the full text read, for records that carry text.
    public var textCutOff: Bool? {
        guard let text, let fullTextBytes else { return nil }
        return fullTextBytes > text.utf8.count
    }

    /// A reading of the focused window, whose text may be the cut-off or timed-out start of a longer full text.
    public static func capture(
        id: UUID = UUID(), at capturedAt: Date, trigger: Trigger, appName: String, bundleID: String?,
        windowTitle: String?, text: String, fullTextBytes: Int, timedOut: Bool
    ) -> SpoolRecord {
        SpoolRecord(
            id: id, capturedAt: capturedAt, kind: .capture, trigger: trigger, appName: appName,
            bundleID: bundleID, windowTitle: windowTitle, text: text,
            fullTextBytes: max(fullTextBytes, text.utf8.count), timedOut: timedOut
        )
    }

    /// A moment a denylisted app, a private browser window or a password-manager page was focused, naming the app and nothing else.
    public static func excluded(
        id: UUID = UUID(), at capturedAt: Date, trigger: Trigger, appName: String, bundleID: String?
    ) -> SpoolRecord {
        SpoolRecord(
            id: id, capturedAt: capturedAt, kind: .excluded, trigger: trigger, appName: appName,
            bundleID: bundleID, windowTitle: nil, text: nil, fullTextBytes: nil, timedOut: nil
        )
    }

    /// The moment capturing was paused.
    public static func paused(id: UUID = UUID(), at capturedAt: Date) -> SpoolRecord {
        SpoolRecord(id: id, capturedAt: capturedAt, kind: .paused)
    }

    /// The moment capturing resumed.
    public static func resumed(id: UUID = UUID(), at capturedAt: Date) -> SpoolRecord {
        SpoolRecord(id: id, capturedAt: capturedAt, kind: .resumed)
    }

    /// The moment the Mac went to sleep.
    public static func slept(id: UUID = UUID(), at capturedAt: Date) -> SpoolRecord {
        SpoolRecord(id: id, capturedAt: capturedAt, kind: .slept)
    }

    /// The moment the Mac woke.
    public static func woke(id: UUID = UUID(), at capturedAt: Date) -> SpoolRecord {
        SpoolRecord(id: id, capturedAt: capturedAt, kind: .woke)
    }

    private init(
        id: UUID, capturedAt: Date, kind: Kind, trigger: Trigger? = nil, appName: String? = nil,
        bundleID: String? = nil, windowTitle: String? = nil, text: String? = nil,
        fullTextBytes: Int? = nil, timedOut: Bool? = nil
    ) {
        self.id = id
        self.capturedAt = capturedAt
        self.kind = kind
        self.trigger = trigger
        self.appName = appName
        self.bundleID = bundleID
        self.windowTitle = windowTitle
        self.text = text
        self.fullTextBytes = fullTextBytes
        self.timedOut = timedOut
    }

    /// The record as one line of JSON with every key present and sorted, without the trailing newline.
    public func jsonLine() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }
}

extension SpoolRecord: Encodable {
    enum CodingKeys: String, CodingKey {
        case version, id, kind, trigger, text
        case capturedAt = "captured_at"
        case appName = "app_name"
        case bundleID = "bundle_id"
        case windowTitle = "window_title"
        case textSHA256 = "text_sha256"
        case fullTextBytes = "full_text_bytes"
        case textCutOff = "text_cut_off"
        case timedOut = "timed_out"
    }

    public func encode(to encoder: any Encoder) throws {
        var line = encoder.container(keyedBy: CodingKeys.self)
        try line.encode(Self.formatVersion, forKey: .version)
        try line.encode(id.uuidString.lowercased(), forKey: .id)
        try line.encode(SpoolTime(capturedAt).iso8601, forKey: .capturedAt)
        try line.encode(kind.rawValue, forKey: .kind)
        try line.encode(trigger?.rawValue, forKey: .trigger)
        try line.encode(appName, forKey: .appName)
        try line.encode(bundleID, forKey: .bundleID)
        try line.encode(windowTitle, forKey: .windowTitle)
        try line.encode(text, forKey: .text)
        try line.encode(textSHA256, forKey: .textSHA256)
        try line.encode(fullTextBytes, forKey: .fullTextBytes)
        try line.encode(textCutOff, forKey: .textCutOff)
        try line.encode(timedOut, forKey: .timedOut)
    }
}

func sha256Hex(_ text: String) -> String {
    SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
}
