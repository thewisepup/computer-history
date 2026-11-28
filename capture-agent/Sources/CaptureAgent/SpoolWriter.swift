import Darwin
import Foundation

/// A record the spool holds as one line of JSON.
public protocol SpoolLine {
    func jsonLine() throws -> Data
}

extension SpoolRecord: SpoolLine {}
extension ScreenshotRecord: SpoolLine {}

/// Where the capture loop appends its records.
public protocol SpoolAppender: AnyObject, Sendable {
    func append(_ record: some SpoolLine) throws
}

/// Appends records to the spool's open file and renames it to a finished file the backend may collect.
public final class SpoolWriter: SpoolAppender, @unchecked Sendable {
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
    private let log: AgentLog
    private let lock = NSLock()
    private var state = SpoolWriterState.notStarted

    public init(directory: URL, now: @escaping @Sendable () -> Date, log: AgentLog) {
        self.directory = directory
        self.now = now
        self.log = log
    }

    deinit {
        switch state {
        case .notStarted:
            break
        case .idle(let spool):
            close(spool.lockFile)
        case .open(let spool, let file, _):
            try? file.close()
            close(spool.lockFile)
        }
    }

    var openFile: URL { directory.appendingPathComponent(Self.openFileName) }

    /// Takes the spool for this process and finishes any open file a previous run left behind.
    @discardableResult
    public func start() throws -> URL? {
        try finish()
    }

    /// Appends the record to the open file as one line, opening a new file if none is open.
    public func append(_ record: some SpoolLine) throws {
        var line = try record.jsonLine()
        line.append(UInt8(ascii: "\n"))
        try lock.withLock {
            try startIfNeeded()
            let file = try openHandle()
            if case .open(_, _, .unknown) = state {
                try dropUnfinishedLine(file)
                handle(.tailRepaired)
            }
            try file.seekToEnd()
            do {
                try file.write(contentsOf: line)
            } catch {
                handle(.writeFailed)
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

    private func handle(_ event: SpoolWriterState.Event) {
        state.handle(event, log: log, .spool)
    }

    private func startIfNeeded() throws {
        guard case .notStarted = state else { return }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        chmod(directory.path, Self.folderMode)
        let lockPath = directory.appendingPathComponent(Self.lockFileName).path
        let descriptor: Int32
        do {
            descriptor = try lockExclusively(lockPath, mode: Self.fileMode)
        } catch is LockHeld {
            throw InUse(directory: directory)
        }
        do {
            fchmod(descriptor, Self.fileMode)
            chmod(openFile.path, Self.fileMode)
            let names = try FileManager.default.contentsOfDirectory(atPath: directory.path)
            let stamps = names.compactMap { name in
                name.hasSuffix(Self.finishedSuffix) ? SpoolTime(fileStamp: name.dropLast(Self.finishedSuffix.count)) : nil
            }
            handle(.started(lockFile: descriptor, lastFinished: stamps.max() ?? SpoolTime(milliseconds: 0)))
        } catch {
            close(descriptor)
            throw error
        }
    }

    private func openHandle() throws -> FileHandle {
        let exists = FileManager.default.fileExists(atPath: openFile.path)
        if case .open(_, let file, _) = state {
            if exists { return file }
            try? file.close()
            handle(.openFileGone)
        }
        if !exists {
            FileManager.default.createFile(atPath: openFile.path, contents: nil, attributes: [.posixPermissions: Self.fileMode])
        }
        let file = try FileHandle(forUpdating: openFile)
        handle(.opened(file, leftover: exists))
        return file
    }

    private func finishLocked() throws -> URL? {
        guard FileManager.default.fileExists(atPath: openFile.path) else {
            if case .open(_, let file, _) = state {
                try? file.close()
                handle(.openFileGone)
            }
            return nil
        }
        let file = try openHandle()
        try dropUnfinishedLine(file)
        handle(.tailRepaired)
        guard try file.seekToEnd() > 0 else { return nil }
        try file.synchronize()
        guard case .open(let spool, _, _) = state else { return nil }
        var tried = spool.lastFinished
        while true {
            let stamp = SpoolTime(milliseconds: max(SpoolTime(now()).milliseconds, tried.milliseconds + 1))
            let finished = directory.appendingPathComponent(stamp.fileStamp + Self.finishedSuffix)
            if renamex_np(openFile.path, finished.path, UInt32(RENAME_EXCL)) == 0 {
                try? file.close()
                handle(.finished(stamp))
                return finished
            }
            guard errno == EEXIST else { throw posixError() }
            tried = stamp
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

/// The spool writer's hold on the spool: not taken yet, taken with no file open, or taken with the open file and whether its last line may be torn.
enum SpoolWriterState: StateMachine {
    struct Spool: Equatable {
        let lockFile: Int32
        let lastFinished: SpoolTime
    }

    enum Tail: Equatable {
        case clean, unknown
    }

    enum Event {
        case started(lockFile: Int32, lastFinished: SpoolTime)
        case opened(FileHandle, leftover: Bool)
        case writeFailed
        case tailRepaired
        case finished(SpoolTime)
        case openFileGone
    }

    static let name = "spool writer"

    case notStarted
    case idle(Spool)
    case open(Spool, FileHandle, tail: Tail)

    func after(_ event: Event) -> SpoolWriterState? {
        switch (self, event) {
        case (.notStarted, .started(let lockFile, let lastFinished)):
            .idle(Spool(lockFile: lockFile, lastFinished: lastFinished))
        case (.idle(let spool), .opened(let file, let leftover)):
            .open(spool, file, tail: leftover ? .unknown : .clean)
        case (.open(let spool, let file, _), .writeFailed):
            .open(spool, file, tail: .unknown)
        case (.open(let spool, let file, _), .tailRepaired):
            .open(spool, file, tail: .clean)
        case (.open(let spool, _, _), .finished(let stamp)):
            .idle(Spool(lockFile: spool.lockFile, lastFinished: stamp))
        case (.open(let spool, _, _), .openFileGone):
            .idle(spool)
        case (.notStarted, .opened), (.notStarted, .writeFailed), (.notStarted, .tailRepaired), (.notStarted, .finished),
             (.notStarted, .openFileGone), (.idle, .started), (.idle, .writeFailed), (.idle, .tailRepaired),
             (.idle, .finished), (.idle, .openFileGone), (.open, .started), (.open, .opened):
            nil
        }
    }
}
