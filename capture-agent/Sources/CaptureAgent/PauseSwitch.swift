import Foundation

/// The file in the agent's folder whose presence means capture is paused, set by the pause and resume commands.
public struct PauseSwitch: Sendable {
    public let file: URL

    public init(file: URL) {
        self.file = file
    }

    public var isPaused: Bool {
        FileManager.default.fileExists(atPath: file.path)
    }

    /// Creates the file, returning false if capture was already paused.
    @discardableResult
    public func pause() throws -> Bool {
        guard !isPaused else { return false }
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data().write(to: file)
        return true
    }

    /// Deletes the file, returning false if capture was not paused.
    @discardableResult
    public func resume() throws -> Bool {
        do {
            try FileManager.default.removeItem(at: file)
            return true
        } catch CocoaError.fileNoSuchFile {
            return false
        }
    }
}

/// Pauses capture until the resume command, across agent restarts and reboots.
public func pauseCapture(_ pause: PauseSwitch) -> CommandOutcome {
    do {
        guard try pause.pause() else { return CommandOutcome(exitCode: 0, message: "Already paused (\(pause.file.path)).") }
    } catch {
        return CommandOutcome(exitCode: 1, message: "Could not pause: \(error.localizedDescription)")
    }
    return CommandOutcome(
        exitCode: 0,
        message: "Paused (\(pause.file.path)). The running agent stops capturing within a second and stays paused, "
            + "even after a restart, until `\(AgentIdentity.executableName) resume`."
    )
}

/// Lets capture start again after a pause.
public func resumeCapture(_ pause: PauseSwitch) -> CommandOutcome {
    do {
        guard try pause.resume() else { return CommandOutcome(exitCode: 0, message: "Not paused (\(pause.file.path)).") }
    } catch {
        return CommandOutcome(exitCode: 1, message: "Could not resume: \(error.localizedDescription)")
    }
    return CommandOutcome(exitCode: 0, message: "Resumed (\(pause.file.path)). The running agent captures again within a second.")
}
