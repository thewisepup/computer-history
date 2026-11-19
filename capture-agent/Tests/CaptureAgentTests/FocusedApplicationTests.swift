import Foundation
import Testing
@testable import CaptureAgent

func describeFake(_ pid: pid_t) -> FocusedApplication? {
    pid == 0 ? nil : FocusedApplication(processIdentifier: pid, bundleIdentifier: "app.\(pid)", bundleURL: nil, name: nil)
}

@Test func prefersTheAccessibilityFocusedApplication() {
    let app = focusedApplication(accessibilityPid: { 7 }, workspacePid: { 9 }, describe: describeFake)
    #expect(app?.processIdentifier == 7)
}

@Test func fallsBackToTheWorkspaceFrontmostApplication() {
    #expect(focusedApplication(accessibilityPid: { nil }, workspacePid: { 9 }, describe: describeFake)?.processIdentifier == 9)
    #expect(focusedApplication(accessibilityPid: { 0 }, workspacePid: { 9 }, describe: describeFake)?.processIdentifier == 9)
    #expect(focusedApplication(accessibilityPid: { nil }, workspacePid: { nil }, describe: describeFake) == nil)
}
