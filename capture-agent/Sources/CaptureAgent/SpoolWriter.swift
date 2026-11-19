import Darwin
import Foundation

/// Appends records to the spool's open file and renames it to a finished file the backend may collect.
public final class SpoolWriter: @unchecked Sendable {
    public static let openFileName = "open.part"
    public static let lockFileName = "agent.lock"
    public static let finishedSuffix = ".jsonl"
    static let folderMode: mode_t = 0o700
    static let fileMode: mode_t = 0o600

    /// Another agent holds the spool's lock.
    public struct InUse: Error, CustomStringConvertible {
        public let directory: URL
        public var description: String { "another agent is writing to \(directory.path)" }
    }

    public let directory: URL
    private let now: @Sendable () -> Date
    private let lock = NSLock()
    private var lockFile: Int32 = -1
    private var handle: FileHandle?
    private var tailMayBeTorn = false
    private var lastFinished = SpoolTime(milliseconds: 0)

    public init(directory: URL, now: @escaping @Sendable () -> Date) {
        self.directory = directory
        self.now = now
    }

    deinit {
        try? handle?.close()
        if lockFile >= 0 { close(lockFile) }
    }

    var openFile: URL { directory.appendingPathComponent(Self.openFileName) }

    /// Takes the spool for this process and finishes any open file a previous run left behind.
    @discardableResult
    public func start() throws -> URL? {
        try finish()
    }

    /// Appends the record to the open file as one line, opening a new file if none is open.
    public func append(_ record: SpoolRecord) throws {
        var line = try record.jsonLine()
        line.append(UInt8(ascii: "\n"))
        try lock.withLock {
            try startIfNeeded()
            let file = try openHandle()
            if tailMayBeTorn {
                try dropUnfinishedLine(file)
                tailMayBeTorn = false
            }
            try file.seekToEnd()
            do {
                try file.write(contentsOf: line)
            } catch {
                tailMayBeTorn = true
                throw error
            }
        }
    }

    /// Renames a non-empty open file to a finished name and returns it, or returns nil if there was nothing to finish.
    @discardableResult
    public func finish() throws -> URL? {
        try lock.withLock {
            try startIfNeeded()
            return try finishLocked()
        }
    }

    private func startIfNeeded() throws {
        guard lockFile < 0 else { return }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        guard chmod(directory.path, Self.folderMode) == 0 else { throw posixError() }
        let lockPath = directory.appendingPathComponent(Self.lockFileName).path
        let descriptor = open(lockPath, O_RDWR | O_CREAT | O_CLOEXEC, Self.fileMode)
        guard descriptor >= 0 else { throw posixError() }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            let error: any Error = errno == EWOULDBLOCK ? InUse(directory: directory) : posixError()
            close(descriptor)
            throw error
        }
        guard fchmod(descriptor, Self.fileMode) == 0,
              chmod(openFile.path, Self.fileMode) == 0 || errno == ENOENT else {
            let error = posixError()
            close(descriptor)
            throw error
        }
        let names = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        let stamps = names.compactMap { name in
            name.hasSuffix(Self.finishedSuffix) ? SpoolTime(fileStamp: name.dropLast(Self.finishedSuffix.count)) : nil
        }
        lastFinished = max(lastFinished, stamps.max() ?? lastFinished)
        lockFile = descriptor
    }

    private func openHandle() throws -> FileHandle {
        if let handle { return handle }
        if !FileManager.default.fileExists(atPath: openFile.path) {
            FileManager.default.createFile(atPath: openFile.path, contents: nil, attributes: [.posixPermissions: Self.fileMode])
        }
        let file = try FileHandle(forUpdating: openFile)
        handle = file
        return file
    }

    private func finishLocked() throws -> URL? {
        guard FileManager.default.fileExists(atPath: openFile.path) else { return nil }
        let file = try openHandle()
        try dropUnfinishedLine(file)
        tailMayBeTorn = false
        guard try file.seekToEnd() > 0 else { return nil }
        try file.synchronize()
        while true {
            let stamp = SpoolTime(milliseconds: max(SpoolTime(now()).milliseconds, lastFinished.milliseconds + 1))
            let finished = directory.appendingPathComponent(stamp.fileStamp + Self.finishedSuffix)
            if renamex_np(openFile.path, finished.path, UInt32(RENAME_EXCL)) == 0 {
                try? file.close()
                handle = nil
                lastFinished = stamp
                return finished
            }
            guard errno == EEXIST else { throw posixError() }
            lastFinished = stamp
        }
    }

    private func dropUnfinishedLine(_ file: FileHandle) throws {
        let size = try file.seekToEnd()
        guard size > 0 else { return }
        try file.seek(toOffset: size - 1)
        if try file.read(upToCount: 1) == Data([UInt8(ascii: "\n")]) { return }
        try file.seek(toOffset: 0)
        let contents = try file.readToEnd() ?? Data()
        let keep = contents.lastIndex(of: UInt8(ascii: "\n")).map { UInt64($0) + 1 } ?? 0
        try file.truncate(atOffset: keep)
    }
}

private func posixError() -> POSIXError {
    POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
}
