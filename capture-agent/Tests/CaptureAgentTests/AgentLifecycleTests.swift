import Foundation
import Testing
@testable import CaptureAgent

final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _prompts: [Bool] = []
    private var _capturingStarted = 0
    private var _stopDeadlines: [DispatchTime] = []
    var dropped: Int? = 0
    let logs = LogRecorder()
    let spool = TempSpool()
    let counts = CaptureCounts()
    var instanceLock: InstanceLock?
    lazy var settings = AgentSettings.load(environment: [
        "COMPUTER_HISTORY_DB": spool.directory.appendingPathComponent("folder/history.db").path,
    ])

    var lines: [String] { logs.records.map(\.message) }
    var prompts: [Bool] { lock.withLock { _prompts } }
    var capturingStarted: Int { lock.withLock { _capturingStarted } }
    var stopDeadlines: [DispatchTime] { lock.withLock { _stopDeadlines } }

    func agent(granted: Bool) -> AgentLifecycle {
        AgentLifecycle(
            report: settings.report,
            instanceLock: instanceLock,
            isPaused: { self.settings.pause.isPaused },
            accessibilityTrusted: { prompt in
                self.lock.withLock { self._prompts.append(prompt) }
                return granted
            },
            spool: spool.writer(),
            counts: counts,
            startCapturing: { self.lock.withLock { self._capturingStarted += 1 } },
            stopCapturing: { deadline in
                self.lock.withLock { self._stopDeadlines.append(deadline) }
                return self.dropped
            },
            log: logs.log
        )
    }
}

@Test func startLogsGrantedAccessibility() {
    let recorder = Recorder()
    recorder.agent(granted: true).start()
    #expect(recorder.lines.first == "started, accessibility granted")
}

@Test func startPromptsOnceAndLogsMissingAccessibility() {
    let recorder = Recorder()
    recorder.agent(granted: false).start()
    #expect(recorder.prompts == [true])
    #expect(recorder.lines.first == "started, accessibility missing, asked macOS to prompt for it")
}

@Test func theMinuteLineChecksAccessibilityWithoutPrompting() {
    let recorder = Recorder()
    let agent = recorder.agent(granted: false)
    agent.start()
    agent.logMinute()
    agent.logMinute()
    #expect(recorder.prompts == [true, false, false])
    let quiet = "heartbeat, accessibility missing, last minute: 0 captures written, 0 excluded, 0 timed out, 0 cut off, slowest read 0.00s, 0 screenshot records queued"
    #expect(recorder.lines.suffix(2) == [quiet, quiet])
}

@Test func theMinuteLineLogsTheCaptureCountsSinceTheLastOne() throws {
    let recorder = Recorder()
    let agent = recorder.agent(granted: true)
    recorder.counts.recordRead(seconds: 0.4)
    recorder.counts.recordExcluded()
    recorder.counts.recordWritten(captureRecord(text: "", fullTextBytes: 0, timedOut: true))
    recorder.counts.recordWritten(captureRecord(text: "ab", fullTextBytes: 9, timedOut: false))
    agent.logMinute()
    agent.logMinute()
    #expect(recorder.lines == [
        "heartbeat, accessibility granted, last minute: 2 captures written, 1 excluded, 1 timed out, 1 cut off, slowest read 0.40s, 0 screenshot records queued",
        "heartbeat, accessibility granted, last minute: 0 captures written, 0 excluded, 0 timed out, 0 cut off, slowest read 0.00s, 0 screenshot records queued",
    ])
}

@Test func startReadiesTheSpoolAndFinishesALeftoverFile() throws {
    let recorder = Recorder()
    try recorder.spool.writeOpenFile(try line(fixtureRecords[0]) + "\n")
    recorder.agent(granted: true).start()
    #expect(recorder.lines.dropFirst(2) == [
        "spool ready at \(recorder.spool.directory.path)",
        "spool finished leftover file 20261118T090000.000Z.jsonl",
    ])
    #expect(try recorder.spool.finishedNames() == ["20261118T090000.000Z.jsonl"])
}

@Test func startLogsASpoolThatCannotBeCreated() throws {
    let recorder = Recorder()
    try Data().write(to: recorder.spool.directory)
    recorder.agent(granted: true).start()
    #expect(recorder.lines.last?.hasPrefix("spool failed to start") == true)
}

@Test func finishSpoolFileFinishesTheOpenFileAndLogsNothing() throws {
    let recorder = Recorder()
    let agent = recorder.agent(granted: true)
    agent.start()
    let logged = recorder.lines
    try agent.spool.append(fixtureRecords[0])
    agent.finishSpoolFile()
    #expect(try recorder.spool.finishedNames() == ["20261118T090000.000Z.jsonl"])
    #expect(recorder.lines == logged)
}

@Test(.timeLimit(.minutes(1))) func runExitsWithoutCapturingOrPromptingWhenAnotherAgentHoldsTheSpool() throws {
    let recorder = Recorder()
    let other = recorder.spool.writer()
    try other.start()
    #expect(recorder.agent(granted: true).run() == 1)
    #expect(recorder.capturingStarted == 0)
    #expect(recorder.prompts.isEmpty)
    #expect(recorder.lines == ["spool failed to start at \(recorder.spool.directory.path): another agent is writing to \(recorder.spool.directory.path), exiting"])
    try other.append(fixtureRecords[0])
    #expect(try other.finish() != nil)
}

@Test(.timeLimit(.minutes(1))) func aSecondAgentExitsWithoutTouchingItsSpoolOrPromptingWhileTheFirstHoldsTheInstanceLock() throws {
    let folder = TempFolder()
    let file = folder.url.appendingPathComponent("account/\(InstanceLock.fileName)")
    let first = Recorder()
    first.instanceLock = InstanceLock(file: file)
    #expect(first.agent(granted: true).start() == .started)
    let second = Recorder()
    second.instanceLock = InstanceLock(file: file)
    #expect(second.agent(granted: true).run() == 1)
    #expect(second.capturingStarted == 0)
    #expect(second.prompts.isEmpty)
    #expect(!FileManager.default.fileExists(atPath: second.spool.directory.path))
    #expect(second.lines == ["instance lock not taken at \(file.path): another agent holds \(file.path), exiting"])
}

@Test func theInstanceLockIsHeldUntilItsHolderLetsGoAndOnlyTheOwnerCanOpenIt() throws {
    let folder = TempFolder()
    let file = folder.url.appendingPathComponent("account/\(InstanceLock.fileName)")
    var first: InstanceLock? = InstanceLock(file: file)
    try first?.take()
    try first?.take()
    #expect(throws: InstanceLock.Held.self) { try InstanceLock(file: file).take() }
    first = nil
    try InstanceLock(file: file).take()
    #expect(try mode(file) == 0o600)
    #expect(try mode(file.deletingLastPathComponent()) == 0o700)
}

private func mode(_ url: URL) throws -> Int {
    try (FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as! NSNumber).intValue & 0o777
}

@Test func startSaysWhetherCapturingMayStart() throws {
    let recorder = Recorder()
    #expect(recorder.agent(granted: true).start() == .started)
    let blocked = Recorder()
    let other = blocked.spool.writer()
    try other.start()
    #expect(blocked.agent(granted: true).start() == .spoolHeldByAnotherAgent)
}

@Test func startLogsWhereTheSettingsCameFromAndEveryProblem() throws {
    let recorder = Recorder()
    let folder = recorder.settings.folder
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    try Data(#"{"idle_threshold_seconds": 1, "colour": "blue"}"#.utf8).write(to: recorder.settings.configPath)
    recorder.settings = AgentSettings.load(environment: ["COMPUTER_HISTORY_DB": folder.appendingPathComponent("history.db").path])
    recorder.agent(granted: true).start()
    #expect(Array(recorder.lines.dropFirst().prefix(3)) == [
        "config read from \(folder.path)/agent-config.json, \(Denylist.builtIn.count) apps denylisted",
        "config problem: unknown key \"colour\" ignored",
        "config problem: idle_threshold_seconds 1 is outside 10–86400, using 180",
    ])
}

@Test func startLogsThatCaptureIsPaused() throws {
    let recorder = Recorder()
    try recorder.settings.pause.pause()
    recorder.agent(granted: true).start()
    #expect(recorder.lines.dropFirst(2).first == "capture is paused, run `\(AgentIdentity.executableName) resume` to capture again")
}

@Test func stoppingGivesTheCaptureThreadAFewSecondsThenFinishesTheSpoolFile() throws {
    let recorder = Recorder()
    recorder.dropped = 2
    let agent = recorder.agent(granted: true)
    agent.start()
    try agent.spool.append(captureRecord(text: "written before the stop", fullTextBytes: 23))
    let before = DispatchTime.now()
    agent.stop()
    let deadline = try #require(recorder.stopDeadlines.first)
    #expect(deadline >= before + AgentLifecycle.stopDrainSeconds)
    #expect(deadline <= DispatchTime.now() + AgentLifecycle.stopDrainSeconds)
    #expect(try recorder.spool.finishedNames().count == 1)
    #expect(recorder.lines.last == "stopping, 2 screenshot records dropped")
}

@Test func stoppingSaysSoWhenTheCaptureThreadDidNotFinish() {
    let recorder = Recorder()
    recorder.dropped = nil
    recorder.agent(granted: true).stop()
    #expect(recorder.lines.last == "stopping, the capture thread did not finish in time")
}

@Test func aCaptureStopWaitsForTheCaptureThreadToFinishAndReturnsWhatItDropped() {
    let stop = CaptureStop()
    let thread = Thread {
        while stop.requestedDeadline == nil { Thread.sleep(forTimeInterval: 0.01) }
        stop.finish(dropped: 3)
    }
    thread.start()
    #expect(stop.stop(by: .now() + 5) == 3)
}

@Test func aCaptureStopGivesUpShortlyAfterTheDeadline() {
    let stop = CaptureStop()
    let started = Date()
    #expect(stop.stop(by: .now() + 0.1) == nil)
    #expect(Date().timeIntervalSince(started) < CaptureStop.grace + 1)
}
