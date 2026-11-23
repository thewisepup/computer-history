import Darwin
import Foundation

/// The lock file that only one capturing agent per account can hold, in the account's real folder whatever the environment says.
public final class InstanceLock: @unchecked Sendable {
    public static let fileName = "agent-instance.lock"

    /// Another agent holds the lock.
    public struct Held: Error, CustomStringConvertible {
        public let file: URL
        public var description: String { "another agent holds \(file.path)" }
    }

    public let file: URL
    private let lock = NSLock()
    private var descriptor: Int32 = -1

    public init(file: URL) {
        self.file = file
    }

    public convenience init(accountHome: URL) {
        self.init(file: AgentSettings.defaultFolder(home: accountHome).appendingPathComponent(Self.fileName))
    }

    deinit {
        if descriptor >= 0 { close(descriptor) }
    }

    /// Takes the lock for the life of this process, throwing Held at once if another agent has it.
    public func take() throws {
        try lock.withLock {
            guard descriptor < 0 else { return }
            try FileManager.default.createDirectory(
                at: file.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
            )
            do {
                descriptor = try lockExclusively(file.path, mode: 0o600)
            } catch is LockHeld {
                throw Held(file: file)
            }
        }
    }
}

struct LockHeld: Error {}

/// Opens the file, creating it with the mode, and locks it without waiting, returning its descriptor.
func lockExclusively(_ path: String, mode: mode_t) throws -> Int32 {
    let descriptor = open(path, O_RDWR | O_CREAT | O_CLOEXEC, mode)
    guard descriptor >= 0 else { throw posixError() }
    guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
        let error: any Error = errno == EWOULDBLOCK ? LockHeld() : posixError()
        close(descriptor)
        throw error
    }
    return descriptor
}

func posixError() -> POSIXError {
    POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
}
