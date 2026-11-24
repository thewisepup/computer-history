import Foundation
import Testing
@testable import CaptureAgent

private func expectTransitions<S: StateMachine>(_ legal: [(S, S.Event, S)], refused: [(S, S.Event)]) {
    for (from, event, to) in legal {
        let logs = LogRecorder()
        var state = from
        let moved = state.handle(event, log: logs.log, .capture)
        #expect(moved, "\(caseName(from)) on \(caseName(event))")
        #expect(state == to, "\(caseName(from)) on \(caseName(event))")
        #expect(logs.records.isEmpty)
    }
    for (from, event) in refused {
        let logs = LogRecorder()
        var state = from
        let moved = state.handle(event, log: logs.log, .capture)
        #expect(!moved, "\(caseName(from)) on \(caseName(event))")
        #expect(state == from, "\(caseName(from)) on \(caseName(event))")
        #expect(logs.records == [
            AgentLog.Record(
                category: .capture, level: .error,
                message: "\(S.name) refused \(caseName(event)) in state \(caseName(from)), state kept", detail: nil
            ),
        ])
    }
}

@Test func theSpoolWriterTakesTheSpoolOpensFinishesAndMarksATornTail() {
    let file = FileHandle.nullDevice
    let spool = SpoolWriterState.Spool(lockFile: 3, lastFinished: SpoolTime(milliseconds: 5))
    let later = SpoolWriterState.Spool(lockFile: 3, lastFinished: SpoolTime(milliseconds: 9))
    let clean = SpoolWriterState.open(spool, file, tail: .clean)
    let unknown = SpoolWriterState.open(spool, file, tail: .unknown)
    expectTransitions(
        [
            (.notStarted, .started(lockFile: 3, lastFinished: SpoolTime(milliseconds: 5)), .idle(spool)),
            (.idle(spool), .opened(file, leftover: false), clean),
            (.idle(spool), .opened(file, leftover: true), unknown),
            (clean, .writeFailed, unknown),
            (unknown, .writeFailed, unknown),
            (unknown, .tailRepaired, clean),
            (clean, .tailRepaired, clean),
            (clean, .finished(SpoolTime(milliseconds: 9)), .idle(later)),
            (unknown, .openFileGone, .idle(spool)),
        ],
        refused: [
            (.notStarted, .opened(file, leftover: false)),
            (.notStarted, .writeFailed),
            (.notStarted, .tailRepaired),
            (.notStarted, .finished(SpoolTime(milliseconds: 9))),
            (.notStarted, .openFileGone),
            (.idle(spool), .started(lockFile: 4, lastFinished: SpoolTime(milliseconds: 0))),
            (.idle(spool), .writeFailed),
            (.idle(spool), .tailRepaired),
            (.idle(spool), .finished(SpoolTime(milliseconds: 9))),
            (.idle(spool), .openFileGone),
            (clean, .started(lockFile: 4, lastFinished: SpoolTime(milliseconds: 0))),
            (clean, .opened(file, leftover: false)),
        ]
    )
}

@Test func sleepIsRecordedThenWakesThroughWakingOnlyWhenRecorded() {
    expectTransitions(
        [
            (SleepState.awake, .willSleep(at: 10), .asleep(since: 10, recorded: false)),
            (.asleep(since: 10, recorded: true), .willSleep(at: 20), .asleep(since: 20, recorded: false)),
            (.waking, .willSleep(at: 20), .asleep(since: 20, recorded: false)),
            (.asleep(since: 10, recorded: false), .recorded, .asleep(since: 10, recorded: true)),
            (.asleep(since: 10, recorded: false), .didWake, .awake),
            (.awake, .didWake, .awake),
            (.asleep(since: 10, recorded: true), .didWake, .waking),
            (.waking, .didWake, .waking),
            (.waking, .woke, .awake),
        ],
        refused: [
            (.awake, .recorded),
            (.asleep(since: 10, recorded: true), .recorded),
            (.waking, .recorded),
            (.awake, .woke),
            (.asleep(since: 10, recorded: false), .woke),
            (.asleep(since: 10, recorded: true), .woke),
        ]
    )
}

@Test func pauseWaitsForItsRecordBeforeCountingAsPausedOrRunning() {
    expectTransitions(
        [
            (PauseState.running, .fileSeen(paused: false), .running),
            (.running, .fileSeen(paused: true), .pausePending),
            (.pausePending, .fileSeen(paused: true), .pausePending),
            (.pausePending, .fileSeen(paused: false), .running),
            (.pausePending, .recorded(paused: true), .paused),
            (.paused, .fileSeen(paused: true), .paused),
            (.paused, .fileSeen(paused: false), .resumePending),
            (.resumePending, .fileSeen(paused: false), .resumePending),
            (.resumePending, .fileSeen(paused: true), .paused),
            (.resumePending, .recorded(paused: false), .running),
        ],
        refused: [
            (.running, .recorded(paused: true)),
            (.running, .recorded(paused: false)),
            (.paused, .recorded(paused: true)),
            (.paused, .recorded(paused: false)),
            (.pausePending, .recorded(paused: false)),
            (.resumePending, .recorded(paused: true)),
        ]
    )
    #expect([PauseState.running, .pausePending, .paused, .resumePending].map(\.silencesCapture) == [false, true, true, false])
}

@Test func oneRequestIsOutstandingUntilItAnswers() {
    expectTransitions(
        [
            (RequestLatch.free, .started(at: 5), .outstanding(since: 5)),
            (.outstanding(since: 5), .answered, .free),
        ],
        refused: [
            (.outstanding(since: 5), .started(at: 6)),
            (.free, .answered),
        ]
    )
}

@Test func keptTextIsReadOrFailedOnce() {
    expectTransitions(
        [
            (KeptTextState.pending, .recognized("hello", fullTextBytes: 5), .read(text: "hello", fullTextBytes: 5)),
            (.pending, .recognitionFailed, .failed),
        ],
        refused: [
            (.read(text: "hello", fullTextBytes: 5), .recognized("secret", fullTextBytes: 6)),
            (.read(text: "hello", fullTextBytes: 5), .recognitionFailed),
            (.failed, .recognized("secret", fullTextBytes: 6)),
            (.failed, .recognitionFailed),
        ]
    )
}

@Test func aRefusedEventLogsNoCapturedText() {
    let logs = LogRecorder()
    var state = KeptTextState.read(text: "my password", fullTextBytes: 11)
    state.handle(.recognized("my other password", fullTextBytes: 17), log: logs.log, .ocr)
    #expect(logs.records.map(\.message) == ["kept text refused recognized in state read, state kept"])
}

@Test func theReminderIsTriedAndForgottenOnceTheGrantIsSeen() {
    let first = Date(timeIntervalSince1970: 1_000)
    let second = Date(timeIntervalSince1970: 2_000)
    let cases: [(PermissionReminder.State, PermissionReminder.State.Event, PermissionReminder.State)] = [
        (.notTried, .tried(at: first), .tried(at: first)),
        (.tried(at: first), .tried(at: second), .tried(at: second)),
        (.tried(at: first), .grantSeen, .notTried),
        (.notTried, .grantSeen, .notTried),
    ]
    for (from, event, to) in cases {
        var state = from
        state.handle(event)
        #expect(state == to)
    }
}

@Test func aPendingFocusChangeKeepsItsStrongestChangeAndFirstTimeUntilTakenOrSilenced() {
    var schedule = CaptureSchedule(settings: CaptureSettings(), start: 0)
    schedule.receive(.focusChanged(.title), at: 10)
    #expect(schedule.pending == CaptureSchedule.PendingChange(change: .title, since: 10, settledAt: 11))
    schedule.receive(.focusChanged(.app), at: 10.5)
    #expect(schedule.pending == CaptureSchedule.PendingChange(change: .app, since: 10, settledAt: 11.5))
    schedule.receive(.focusChanged(.window), at: 10.7)
    #expect(schedule.pending == CaptureSchedule.PendingChange(change: .app, since: 10, settledAt: 11.7))
    #expect(schedule.takeDue(at: 11.8) == .app)
    #expect(schedule.pending == nil)
    schedule.receive(.focusChanged(.window), at: 20)
    schedule.receive(.paused(true), at: 20.5)
    #expect(schedule.pending == nil)
    #expect(schedule.silence == [.paused])
    schedule.receive(.presence(Presence(idleSeconds: 0, locked: true, asleep: false)), at: 21)
    #expect(schedule.silence == [.paused, .locked])
    schedule.receive(.paused(false), at: 22)
    #expect(schedule.silence == [.locked])
}
