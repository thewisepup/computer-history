import Foundation
import Testing
@testable import CaptureAgent

final class LogRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _records: [AgentLog.Record] = []

    var records: [AgentLog.Record] { lock.withLock { _records } }

    var log: AgentLog {
        AgentLog { record in self.lock.withLock { self._records.append(record) } }
    }
}

@Test func lifecycleAndSpoolLinesCarryTheirCategoryAndLevel() throws {
    let recorder = Recorder()
    let agent = recorder.agent(granted: true)
    agent.start()
    agent.logMinute()
    let records = recorder.logs.records
    #expect(records.first == AgentLog.Record(category: .lifecycle, level: .notice, message: "started, accessibility granted", detail: nil))
    #expect(records.contains(
        AgentLog.Record(category: .spool, level: .info, message: "spool ready at \(recorder.spool.directory.path)", detail: nil)
    ))
    let heartbeat = try #require(records.last)
    #expect(heartbeat.category == .lifecycle && heartbeat.level == .notice)
    #expect(heartbeat.message.hasPrefix("heartbeat"))
}

@Test func aCapturedTitleTravelsOnlyAsThePrivateDetail() throws {
    let fixture = LoopFixture()
    fixture.focus.notes.attributes["AXTitle"] = "Quarterly layoffs draft"
    fixture.run(for: 2)
    let records = fixture.logs.records
    #expect(records.contains(AgentLog.Record(
        category: .capture, level: .debug, message: "captured com.apple.TextEdit on heartbeat, 5 text bytes", detail: "Quarterly layoffs draft"
    )))
    #expect(!records.contains { $0.message.contains("Quarterly") || $0.message.contains("hello") })
}
