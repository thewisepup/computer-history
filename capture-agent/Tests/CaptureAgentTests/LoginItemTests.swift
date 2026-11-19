import ServiceManagement
import Testing
@testable import CaptureAgent

struct Refused: Error {}

final class FakeLoginItem: LoginItemService {
    var status: SMAppService.Status
    var statusAfterRegister: SMAppService.Status
    var registerFails = false
    var unregisterFails = false
    var calls: [String] = []

    init(status: SMAppService.Status = .notRegistered, statusAfterRegister: SMAppService.Status = .enabled) {
        self.status = status
        self.statusAfterRegister = statusAfterRegister
    }

    func register() throws {
        calls.append("register")
        status = statusAfterRegister
        if registerFails { throw Refused() }
    }

    func unregister() throws {
        calls.append("unregister")
        if unregisterFails { throw Refused() }
        status = .notRegistered
    }
}

@Test func installRegistersAndReportsEnabled() {
    let service = FakeLoginItem()
    let outcome = installLoginItem(service)
    #expect(service.calls == ["register"])
    #expect(outcome.exitCode == 0)
    #expect(outcome.message.contains("every login"))
}

@Test func installSaysWhenApprovalIsNeeded() {
    let service = FakeLoginItem(statusAfterRegister: .requiresApproval)
    let outcome = installLoginItem(service)
    #expect(outcome.exitCode == 2)
    #expect(outcome.message.contains("Login Items"))
}

@Test func installSaysWhenApprovalIsNeededEvenIfRegisterThrows() {
    let service = FakeLoginItem(statusAfterRegister: .requiresApproval)
    service.registerFails = true
    #expect(installLoginItem(service).exitCode == 2)
}

@Test func installReportsRegistrationFailure() {
    let service = FakeLoginItem(statusAfterRegister: .notRegistered)
    service.registerFails = true
    let outcome = installLoginItem(service)
    #expect(outcome.exitCode == 1)
    #expect(outcome.message.contains("Could not register"))
}

@Test func installFailsWhenThePlistIsMissing() {
    let outcome = installLoginItem(FakeLoginItem(statusAfterRegister: .notFound))
    #expect(outcome.exitCode == 1)
    #expect(outcome.message.contains("missing from the app bundle"))
}

@Test func uninstallUnregistersAnInstalledAgent() {
    let service = FakeLoginItem(status: .enabled)
    let outcome = uninstallLoginItem(service)
    #expect(service.calls == ["unregister"])
    #expect(service.status == .notRegistered)
    #expect(outcome.exitCode == 0)
}

@Test func uninstallUnregistersAnAgentAwaitingApproval() {
    let service = FakeLoginItem(status: .requiresApproval)
    _ = uninstallLoginItem(service)
    #expect(service.calls == ["unregister"])
}

@Test func uninstallOfAnAbsentAgentDoesNothing() {
    let service = FakeLoginItem(status: .notRegistered)
    let outcome = uninstallLoginItem(service)
    #expect(service.calls.isEmpty)
    #expect(outcome.exitCode == 0)
}

@Test func uninstallReportsFailure() {
    let service = FakeLoginItem(status: .enabled)
    service.unregisterFails = true
    #expect(uninstallLoginItem(service).exitCode == 1)
}

@Test func statusDescribesTheLoginItemAndThePause() {
    #expect(agentStatus(FakeLoginItem(status: .enabled), paused: false).message
        == "Login item: enabled, starts at login.\nCapture: not paused.")
    #expect(agentStatus(FakeLoginItem(status: .notRegistered), paused: true).message
        == "Login item: not installed.\nCapture: paused, run `\(AgentIdentity.executableName) resume` to capture again.")
}

@Test func installSucceedsIfRegisterThrowsForAnEnabledItem() {
    let service = FakeLoginItem(status: .enabled)
    service.registerFails = true
    #expect(installLoginItem(service).exitCode == 0)
}

@Test func uninstallWithoutABundledPlistDoesNothing() {
    let service = FakeLoginItem(status: .notFound)
    #expect(uninstallLoginItem(service).exitCode == 0)
    #expect(service.calls.isEmpty)
}
