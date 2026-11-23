import Darwin
import Foundation

/// The lock file that allows one capturing agent per account.
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
