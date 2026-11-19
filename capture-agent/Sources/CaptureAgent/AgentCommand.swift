/// The commands the agent binary accepts on its command line.
public enum AgentCommand: Equatable, Sendable {
    case run
    case install
    case uninstall
    case status
    case usage

    public init(arguments: [String]) {
        switch arguments {
        case [], ["run"]: self = .run
        case ["install"]: self = .install
        case ["uninstall"]: self = .uninstall
        case ["status"]: self = .status
        default: self = .usage
        }
    }
}

/// What a command prints and the exit code it ends with.
public struct CommandOutcome: Equatable, Sendable {
    public let exitCode: Int32
    public let message: String

    public static let usage = CommandOutcome(
        exitCode: 64,
        message: "usage: \(AgentIdentity.executableName) [run | install | uninstall | status]"
    )
}
