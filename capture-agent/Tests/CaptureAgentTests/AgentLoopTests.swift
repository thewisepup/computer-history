import Foundation
import Testing
@testable import CaptureAgent

final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _lines: [String] = []
    private var _prompts: [Bool] = []
    let spool = TempSpool()

    var lines: [String] { lock.withLock { _lines } }
    var prompts: [Bool] { lock.withLock { _prompts } }

    func agent(granted: Bool) -> AgentLoop {
        AgentLoop(
            accessibilityTrusted: { prompt in
                self.lock.withLock { self._prompts.append(prompt) }
                return granted
            },
            spool: spool.writer(),
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

@Test func heartbeatChecksAccessibilityWithoutPrompting() {
    let recorder = Recorder()
    let agent = recorder.agent(granted: false)
    agent.start()
    agent.heartbeat()
    agent.heartbeat()
    #expect(recorder.prompts == [true, false, false])
    #expect(recorder.lines.suffix(2) == ["heartbeat, accessibility missing", "heartbeat, accessibility missing"])
}

@Test func startReadiesTheSpoolAndFinishesALeftoverFile() throws {
    let recorder = Recorder()
    try recorder.spool.writeOpenFile(try line(fixtureRecords[0]) + "\n")
    recorder.agent(granted: true).start()
    #expect(recorder.lines.dropFirst() == [
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
        "spool failed to start at \(recorder.spool.directory.path): another agent is writing to \(recorder.spool.directory.path)",
        "spool failed to finish the open file: another agent is writing to \(recorder.spool.directory.path)",
    ])
}
