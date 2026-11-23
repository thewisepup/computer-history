import Foundation

struct CaptureScript: Decodable, Equatable {
    let start: Date
    let apps: [String: App]
    let steps: [Step]

    struct App: Decodable, Equatable {
        let name: String
        let bundleID: String?
        let focusedWindow: String?
        let windows: [String: Node]

        enum CodingKeys: String, CodingKey, CaseIterable {
            case name, windows
            case bundleID = "bundle_id"
            case focusedWindow = "focused_window"
        }

        init(from decoder: any Decoder) throws {
            let app = try strictContainer(decoder, CodingKeys.self)
            name = try app.decode(String.self, forKey: .name)
            bundleID = try app.decodeIfPresent(String.self, forKey: .bundleID)
            focusedWindow = try app.decodeIfPresent(String.self, forKey: .focusedWindow)
            windows = try app.decode([String: Node].self, forKey: .windows)
        }
    }

    struct Node: Decodable, Equatable {
        let role: String
        let id: String?
        let title: String?
        let subrole: String?
        let description: String?
        let value: String?
        let document: String?
        let url: String?
        let `repeat`: Int
        let hangs: [String]
        let recognizedText: String?
        let children: [Node]

        enum CodingKeys: String, CodingKey, CaseIterable {
            case role, id, title, subrole, description, value, document, url, `repeat`, hangs, children
            case recognizedText = "recognized_text"
        }

        init(from decoder: any Decoder) throws {
            let node = try strictContainer(decoder, CodingKeys.self)
            role = try node.decode(String.self, forKey: .role)
            id = try node.decodeIfPresent(String.self, forKey: .id)
            title = try node.decodeIfPresent(String.self, forKey: .title)
            subrole = try node.decodeIfPresent(String.self, forKey: .subrole)
            description = try node.decodeIfPresent(String.self, forKey: .description)
            value = try node.decodeIfPresent(String.self, forKey: .value)
            document = try node.decodeIfPresent(String.self, forKey: .document)
            url = try node.decodeIfPresent(String.self, forKey: .url)
            `repeat` = try node.decodeIfPresent(Int.self, forKey: .repeat) ?? 1
            hangs = try node.decodeIfPresent([String].self, forKey: .hangs) ?? []
            recognizedText = try node.decodeIfPresent(String.self, forKey: .recognizedText)
            children = try node.decodeIfPresent([Node].self, forKey: .children) ?? []
        }

        var attributes: [String: String] {
            let value = value.map { String(repeating: $0, count: max(0, self.repeat)) }
            let pairs: [(String, String?)] = [
                ("AXRole", role), ("AXTitle", title), ("AXSubrole", subrole), ("AXDescription", description), ("AXValue", value),
                ("AXDocument", document), ("AXURL", url),
            ]
            return Dictionary(uniqueKeysWithValues: pairs.compactMap { key, value in value.map { (key, $0) } })
        }
    }

    struct Step: Decodable, Equatable {
        let at: TimeInterval
        let action: Action

        enum CodingKeys: String, CodingKey, CaseIterable {
            case at, focus, pause, resume, presence, end, crash
            case focusWindow = "focus_window"
            case setTitle = "set_title"
            case focusElement = "focus_element"
            case windowImage = "window_image"
        }

        init(from decoder: any Decoder) throws {
            let step = try strictContainer(decoder, CodingKeys.self)
            at = try step.decode(TimeInterval.self, forKey: .at)
            let actions = step.allKeys.filter { $0 != .at }
            guard actions.count == 1, let key = actions.first else {
                throw DecodingError.dataCorrupted(.init(
                    codingPath: decoder.codingPath, debugDescription: "the step at \(at)s needs exactly one action"
                ))
            }
            action = switch key {
            case .focus: .focus(try step.decode(String.self, forKey: key))
            case .focusWindow: .focusWindow(try step.decode(WindowRef.self, forKey: key))
            case .setTitle: .setTitle(try step.decode(TitleChange.self, forKey: key))
            case .focusElement: .focusElement(try step.decode(ElementRef.self, forKey: key))
            case .windowImage: .windowImage(try step.decode(WindowImageAnswer.self, forKey: key))
            case .presence: .presence(try step.decode(PresenceChange.self, forKey: key).presence)
            case .pause: try Self.flag(.pause, step, key)
            case .resume: try Self.flag(.resume, step, key)
            case .end: try Self.flag(.end, step, key)
            case .crash: try Self.flag(.crash, step, key)
            case .at: preconditionFailure("at is not an action")
            }
        }

        private static func flag(_ action: Action, _ step: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) throws -> Action {
            guard try step.decode(Bool.self, forKey: key) else {
                throw DecodingError.dataCorruptedError(forKey: key, in: step, debugDescription: "\(key.stringValue) must be true")
            }
            return action
        }
    }

    enum Action: Equatable {
        case focus(String)
        case focusWindow(WindowRef)
        case setTitle(TitleChange)
        case focusElement(ElementRef)
        case windowImage(WindowImageAnswer)
        case presence(Presence)
        case pause
        case resume
        case end
        case crash
    }

    struct WindowRef: Decodable, Equatable {
        let app: String
        let window: String
    }

    /// The element an app's focus moves to, by its id in one of the app's windows; neither window nor element clears the focus.
    struct ElementRef: Decodable, Equatable {
        let app: String
        let window: String?
        let element: String?
    }

    /// What ScreenCaptureKit gives for a picture of the focused window from this step on.
    enum WindowImageAnswer: String, Decodable, Equatable {
        case picture
        case noPermission = "no-permission"
        case failed
    }

    struct TitleChange: Decodable, Equatable {
        let app: String
        let window: String
        let title: String
    }

    struct PresenceChange: Decodable {
        let presence: Presence

        enum CodingKeys: String, CodingKey, CaseIterable {
            case locked, asleep
            case idleSeconds = "idle_seconds"
        }

        init(from decoder: any Decoder) throws {
            let change = try strictContainer(decoder, CodingKeys.self)
            presence = Presence(
                idleSeconds: try change.decodeIfPresent(TimeInterval.self, forKey: .idleSeconds) ?? 0,
                locked: try change.decodeIfPresent(Bool.self, forKey: .locked) ?? false,
                asleep: try change.decodeIfPresent(Bool.self, forKey: .asleep) ?? false
            )
        }
    }

    enum CodingKeys: String, CodingKey, CaseIterable {
        case start, apps, steps
    }

    init(from decoder: any Decoder) throws {
        let script = try strictContainer(decoder, CodingKeys.self)
        let start = try script.decode(String.self, forKey: .start)
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: start) else {
            throw DecodingError.dataCorruptedError(
                forKey: .start, in: script, debugDescription: "start \(start) is not UTC ISO-8601 with milliseconds"
            )
        }
        self.start = date
        apps = try script.decode([String: App].self, forKey: .apps)
        steps = try script.decode([Step].self, forKey: .steps)
    }

    static func load(_ file: URL) throws -> CaptureScript {
        try JSONDecoder().decode(CaptureScript.self, from: Data(contentsOf: file))
    }
}

private struct AnyKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }
    init(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

private func strictContainer<Key: CodingKey & CaseIterable>(
    _ decoder: any Decoder, _: Key.Type
) throws -> KeyedDecodingContainer<Key> {
    let known = Set(Key.allCases.map(\.stringValue))
    let unknown = try decoder.container(keyedBy: AnyKey.self).allKeys.map(\.stringValue).filter { !known.contains($0) }
    guard unknown.isEmpty else {
        throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "unknown keys \(unknown.sorted())"))
    }
    return try decoder.container(keyedBy: Key.self)
}
