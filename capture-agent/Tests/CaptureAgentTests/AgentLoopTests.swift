import Foundation
import Testing
@testable import CaptureAgent

final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _lines: [String] = []
    private var _prompts: [Bool] = []

    var lines: [String] { lock.withLock { _lines } }
    var prompts: [Bool] { lock.withLock { _prompts } }

    func agent(granted: Bool) -> AgentLoop {
        AgentLoop(
            accessibilityTrusted: { prompt in
                self.lock.withLock { self._prompts.append(prompt) }
                return granted
            },
            log: { line in self.lock.withLock { self._lines.append(line) } }
        )
    }
}

@Test func startLogsGrantedAccessibility() {
    let recorder = Recorder()
    recorder.agent(granted: true).start()
    #expect(recorder.lines == ["started, accessibility granted"])
}

@Test func startPromptsOnceAndLogsMissingAccessibility() {
    let recorder = Recorder()
    recorder.agent(granted: false).start()
    #expect(recorder.prompts == [true])
    #expect(recorder.lines == ["started, accessibility missing, asked macOS to prompt for it"])
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
