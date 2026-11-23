import Darwin

/// The commands the agent binary accepts on its command line.
public enum AgentCommand: Equatable, Sendable {
    case run
    case install
    case uninstall
    case status
    case pause
    case resume
    case checkConfig
    case requestScreenRecording
    case scriptedSession(script: String)
    case usage

    public init(arguments: [String]) {
        switch arguments {
        case [], ["run"]: self = .run
        case ["install"]: self = .install
        case ["uninstall"]: self = .uninstall
        case ["status"]: self = .status
        case ["pause"]: self = .pause
        case ["resume"]: self = .resume
        case ["check-config"]: self = .checkConfig
        case ["request-screen-recording"]: self = .requestScreenRecording
        case _ where arguments.count == 2 && arguments[0] == "scripted-session": self = .scriptedSession(script: arguments[1])
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
        message: "usage: \(AgentIdentity.executableName) [run | install | uninstall | status | pause | resume | check-config | request-screen-recording | scripted-session <script.json>]"
    )

    public static let noAccountHome = CommandOutcome(exitCode: 1, message: "the user database has no home folder for user \(getuid())")
}
