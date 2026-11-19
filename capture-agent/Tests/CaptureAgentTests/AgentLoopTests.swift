import Foundation
import Testing
@testable import CaptureAgent

final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _lines: [String] = []
    private var _prompts: [Bool] = []
    let spool = TempSpool()
    let counts = CaptureCounts()
    lazy var settings = AgentSettings.load(environment: [
        "COMPUTER_HISTORY_DB": spool.directory.appendingPathComponent("folder/history.db").path,
    ])

    var lines: [String] { lock.withLock { _lines } }
    var prompts: [Bool] { lock.withLock { _prompts } }

    func agent(granted: Bool) -> AgentLoop {
        AgentLoop(
            report: settings.report,
            isPaused: { self.settings.pause.isPaused },
            accessibilityTrusted: { prompt in
                self.lock.withLock { self._prompts.append(prompt) }
                return granted
            },
            spool: spool.writer(),
            counts: counts,
            startCapturing: {},
            log: { line in self.lock.withLock { self._lines.append(line) } }
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
    let quiet = "heartbeat, accessibility missing, last minute: 0 captures written, 0 excluded, 0 timed out, 0 cut off, slowest read 0.00s"
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
        "heartbeat, accessibility granted, last minute: 2 captures written, 1 excluded, 1 timed out, 1 cut off, slowest read 0.40s",
        "heartbeat, accessibility granted, last minute: 0 captures written, 0 excluded, 0 timed out, 0 cut off, slowest read 0.00s",
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

@Test func finishSpoolFileLogsASpoolHeldByAnotherAgent() throws {
    let recorder = Recorder()
    let other = recorder.spool.writer()
    try other.start()
    let agent = recorder.agent(granted: true)
    agent.start()
    agent.finishSpoolFile()
    #expect(recorder.lines.suffix(2) == [
        "spool failed to start at \(recorder.spool.directory.path): another agent is writing to \(recorder.spool.directory.path), not capturing",
        "spool failed to finish the open file: another agent is writing to \(recorder.spool.directory.path)",
    ])
}

@Test func startSaysWhetherCapturingMayStart() throws {
    let recorder = Recorder()
    #expect(recorder.agent(granted: true).start())
    let blocked = Recorder()
    let other = blocked.spool.writer()
    try other.start()
    #expect(!blocked.agent(granted: true).start())
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
