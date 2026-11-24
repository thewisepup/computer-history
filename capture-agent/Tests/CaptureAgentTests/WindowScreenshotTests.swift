import CoreGraphics
import Foundation
import Testing
@testable import CaptureAgent

let editorFrame = CGRect(x: 100, y: 50, width: 1200, height: 800)

func candidate(_ id: CGWindowID, pid: pid_t = 100, _ frame: CGRect = editorFrame, title: String? = nil) -> WindowCandidate {
    WindowCandidate(id: id, processIdentifier: pid, frame: frame, title: title)
}

func focused(_ frame: CGRect = editorFrame, title: String? = "Notes") -> FocusedWindow {
    FocusedWindow(processIdentifier: 100, title: title, frame: frame)
}

@Test func theFocusedWindowIsFoundByItsFrameWhateverItsTitle() {
    let others = [candidate(1, CGRect(x: 0, y: 0, width: 1200, height: 800), title: "Notes"), candidate(2, pid: 200)]
    #expect(matchWindow(focused(title: nil), among: others + [candidate(3, title: "Other")]) == 3)
    #expect(matchWindow(focused(title: "Notes"), among: others + [candidate(3, title: "Other")]) == 3)
}

@Test func aFocusedFloatingPanelIsPhotographedNotTheMainWindow() {
    let panel = CGRect(x: 400, y: 300, width: 300, height: 200)
    #expect(matchWindow(focused(panel, title: "Find"), among: [candidate(1, title: "Notes"), candidate(2, panel, title: "Find")]) == 2)
}

@Test func windowsWithTheSameFrameAreToldApartByTitleOrNotAtAll() {
    let stacked = [candidate(1, title: "Notes"), candidate(2, title: "Inbox")]
    #expect(matchWindow(focused(title: "Inbox"), among: stacked) == 2)
    #expect(matchWindow(focused(title: "Drafts"), among: stacked) == nil)
    #expect(matchWindow(focused(title: nil), among: stacked) == nil)
    #expect(matchWindow(focused(title: "Notes"), among: stacked + [candidate(3, title: "Notes")]) == nil)
}

@Test func aFrameOffByMoreThanRoundingMatchesNothing() {
    #expect(matchWindow(focused(), among: [candidate(1, editorFrame.offsetBy(dx: 0.5, dy: -1))]) == 1)
    #expect(matchWindow(focused(), among: [candidate(1, editorFrame.offsetBy(dx: 10, dy: 0))]) == nil)
    #expect(matchWindow(focused(), among: [candidate(1, pid: 200)]) == nil)
    #expect(matchWindow(focused(), among: []) == nil)
}

@Test(arguments: [
    (CGSize(width: 1440, height: 900), 2.0, 1440, 1440, 900),
    (CGSize(width: 800, height: 600), 1.0, 1440, 800, 600),
    (CGSize(width: 1000, height: 3000), 2.0, 1440, 480, 1440),
    (CGSize(width: 1200, height: 800), 2.0, 4096, 2400, 1600),
])
func theStillIsRequestedAtTheLongEdgeAndNeverAboveNativeSize(
    points: CGSize, scale: Double, longEdge: Int, width: Int, height: Int
) {
    let size = captureSize(of: points, pixelScale: scale, longEdge: longEdge)
    #expect(size.width == width && size.height == height)
}

final class HeldAnswer: @unchecked Sendable {
    var answer: (@Sendable (WindowImage) -> Void)?
    var starts = 0
}

@Test func aHungRequestBlocksOnceThenLaterCapturesFailAtOnceUntilItAnswers() {
    let requests = OneRequestAtATime(log: AgentLog { _ in }, .screenshots)
    let held = HeldAnswer()
    let hang: (@escaping @Sendable (WindowImage) -> Void) -> Void = { answer in
        held.starts += 1
        held.answer = answer
    }
    let first = Date()
    guard case .failed = requests.run(timeout: 0.05, otherwise: WindowImage.failed, hang) else { Issue.record("a hung request must fail"); return }
    #expect(Date().timeIntervalSince(first) >= 0.05)
    let second = Date()
    guard case .failed = requests.run(timeout: 5, otherwise: WindowImage.failed, hang) else { Issue.record("a second request must fail"); return }
    #expect(Date().timeIntervalSince(second) < 1)
    #expect(held.starts == 1)
    held.answer?(.noPermission)
    guard case .noPermission = requests.run(timeout: 5, otherwise: WindowImage.failed, { $0(.noPermission) }) else { Issue.record("an answered gate must run again"); return }
    #expect(held.starts == 1)
}
