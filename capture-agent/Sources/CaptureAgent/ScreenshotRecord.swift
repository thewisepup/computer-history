import Foundation

/// One screenshot spool record: what became of the screenshot taken with a capture, and its recognized text.
public struct ScreenshotRecord: Equatable, Sendable {
    public static let kind = "screenshot"

    public enum Status: String, CaseIterable, Sendable {
        case kept, duplicate
        case secureField = "secure-field"
        case noPermission = "no-permission"
        case failed
    }

    public let id: UUID
    public let captureID: UUID
    public let capturedAt: Date
    public let status: Status
    public let appName: String?
    public let bundleID: String?
    public let windowTitle: String?
    public let imagePath: String?
    public let imageBytes: Int?
    public let perceptualHash: String?
    public private(set) var text: String?
    public private(set) var fullTextBytes: Int?

    /// The lowercase hex SHA-256 of the recognized text as UTF-8, for records that carry text.
    public var textSHA256: String? { text.map(sha256Hex) }

    /// Whether the recognized text is shorter than the full text recognized, for records that carry text.
    public var textCutOff: Bool? {
        guard let text, let fullTextBytes else { return nil }
        return fullTextBytes > text.utf8.count
    }

    /// A new image was saved at the path, relative to the data folder.
    public static func kept(
        id: UUID = UUID(), of capture: SpoolRecord, imagePath: String, imageBytes: Int, perceptualHash: String,
        text: String, fullTextBytes: Int
    ) -> ScreenshotRecord {
        ScreenshotRecord(
            id: id, capture: capture, status: .kept, imagePath: imagePath, imageBytes: imageBytes,
            perceptualHash: perceptualHash, text: text, fullTextBytes: fullTextBytes
        )
    }

    /// The image matched the window's last kept image, whose path and recognized text it carries beside its own hash.
    public static func duplicate(
        id: UUID = UUID(), of capture: SpoolRecord, imagePath: String, perceptualHash: String, text: String,
        fullTextBytes: Int
    ) -> ScreenshotRecord {
        ScreenshotRecord(
            id: id, capture: capture, status: .duplicate, imagePath: imagePath, perceptualHash: perceptualHash,
            text: text, fullTextBytes: fullTextBytes
        )
    }

    /// No screenshot was taken because a password field was focused.
    public static func secureField(id: UUID = UUID(), of capture: SpoolRecord) -> ScreenshotRecord {
        ScreenshotRecord(id: id, capture: capture, status: .secureField)
    }

    /// No screenshot was taken because the Screen Recording grant is missing.
    public static func noPermission(id: UUID = UUID(), of capture: SpoolRecord) -> ScreenshotRecord {
        ScreenshotRecord(id: id, capture: capture, status: .noPermission)
    }

    /// The screenshot could not be taken for any other reason.
    public static func failed(id: UUID = UUID(), of capture: SpoolRecord) -> ScreenshotRecord {
        ScreenshotRecord(id: id, capture: capture, status: .failed)
    }

    private init(
        id: UUID, capture: SpoolRecord, status: Status, imagePath: String? = nil, imageBytes: Int? = nil,
        perceptualHash: String? = nil, text: String? = nil, fullTextBytes: Int? = nil
    ) {
        self.id = id
        self.captureID = capture.id
        self.capturedAt = capture.capturedAt
        self.status = status
        self.appName = capture.appName
        self.bundleID = capture.bundleID
        self.windowTitle = capture.windowTitle
        self.imagePath = imagePath
        self.imageBytes = imageBytes
        self.perceptualHash = perceptualHash
        self.text = text
        self.fullTextBytes = text.map { max(fullTextBytes ?? 0, $0.utf8.count) }
    }

    /// The same record carrying the recognized text and the full length recognized.
    func withText(_ text: String, fullTextBytes: Int) -> ScreenshotRecord {
        var record = self
        record.text = text
        record.fullTextBytes = max(fullTextBytes, text.utf8.count)
        return record
    }

    /// The record as one line of JSON with every key present and sorted, without the trailing newline.
    public func jsonLine() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }
}

extension ScreenshotRecord: Encodable {
    enum CodingKeys: String, CodingKey {
        case version, id, kind, status, text
        case captureID = "capture_id"
        case capturedAt = "captured_at"
        case appName = "app_name"
        case bundleID = "bundle_id"
        case windowTitle = "window_title"
        case imagePath = "image_path"
        case imageBytes = "image_bytes"
        case perceptualHash = "perceptual_hash"
        case textSHA256 = "text_sha256"
        case fullTextBytes = "full_text_bytes"
        case textCutOff = "text_cut_off"
    }

    public func encode(to encoder: any Encoder) throws {
        var line = encoder.container(keyedBy: CodingKeys.self)
        try line.encode(SpoolRecord.formatVersion, forKey: .version)
        try line.encode(id.uuidString.lowercased(), forKey: .id)
        try line.encode(Self.kind, forKey: .kind)
        try line.encode(captureID.uuidString.lowercased(), forKey: .captureID)
        try line.encode(SpoolTime(capturedAt).iso8601, forKey: .capturedAt)
        try line.encode(status.rawValue, forKey: .status)
        try line.encode(appName, forKey: .appName)
        try line.encode(bundleID, forKey: .bundleID)
        try line.encode(windowTitle, forKey: .windowTitle)
        try line.encode(imagePath, forKey: .imagePath)
        try line.encode(imageBytes, forKey: .imageBytes)
        try line.encode(perceptualHash, forKey: .perceptualHash)
        try line.encode(text, forKey: .text)
        try line.encode(textSHA256, forKey: .textSHA256)
        try line.encode(fullTextBytes, forKey: .fullTextBytes)
        try line.encode(textCutOff, forKey: .textCutOff)
    }
}
