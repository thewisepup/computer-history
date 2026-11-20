import os

/// The agent's log: each record has a category, a level, a public message and an optional private detail, handed to one write closure.
public struct AgentLog: Sendable {
    public enum Category: String, CaseIterable, Sendable {
        case lifecycle, capture, spool, screenshots, ocr
    }

    public enum Level: Sendable {
        case debug, info, notice, error
    }

    public struct Record: Equatable, Sendable {
        public let category: Category
        public let level: Level
        public let message: String
        public let detail: String?
    }

    private let write: @Sendable (Record) -> Void

    public init(write: @escaping @Sendable (Record) -> Void) {
        self.write = write
    }

    /// Writes to the unified log under the agent's bundle id, one category per `Category`, with the detail marked private.
    public static func unified() -> AgentLog {
        let loggers = Dictionary(uniqueKeysWithValues: Category.allCases.map {
            ($0, Logger(subsystem: AgentIdentity.bundleIdentifier, category: $0.rawValue))
        })
        return AgentLog { record in
            guard let logger = loggers[record.category] else { return }
            let type: OSLogType = switch record.level {
            case .debug: .debug
            case .info: .info
            case .notice: .default
            case .error: .error
            }
            if let detail = record.detail {
                logger.log(level: type, "\(record.message, privacy: .public) \(detail, privacy: .private)")
            } else {
                logger.log(level: type, "\(record.message, privacy: .public)")
            }
        }
    }

    /// Prints each message on its own line, leaving out the private detail.
    public static let standardOutput = AgentLog { print($0.message) }

    func debug(_ category: Category, _ message: String, private detail: String? = nil) {
        write(Record(category: category, level: .debug, message: message, detail: detail))
    }

    func info(_ category: Category, _ message: String, private detail: String? = nil) {
        write(Record(category: category, level: .info, message: message, detail: detail))
    }

    func notice(_ category: Category, _ message: String, private detail: String? = nil) {
        write(Record(category: category, level: .notice, message: message, detail: detail))
    }

    func error(_ category: Category, _ message: String, private detail: String? = nil) {
        write(Record(category: category, level: .error, message: message, detail: detail))
    }
}
