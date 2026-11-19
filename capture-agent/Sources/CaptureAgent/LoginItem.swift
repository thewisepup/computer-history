import ServiceManagement

/// The parts of SMAppService that the install, uninstall and status commands use.
public protocol LoginItemService {
    var status: SMAppService.Status { get }
    func register() throws
    func unregister() throws
}

extension SMAppService: LoginItemService {}

private let approvalNeeded = CommandOutcome(
    exitCode: 2,
    message: "Registered, but macOS needs approval: open System Settings > General > "
        + "Login Items & Extensions and turn on Computer History Agent."
)

/// Registers the agent as a login item and reports whether macOS enabled it.
public func installLoginItem(_ service: some LoginItemService) -> CommandOutcome {
    do {
        try service.register()
    } catch where service.status != .enabled && service.status != .requiresApproval {
        return CommandOutcome(exitCode: 1, message: "Could not register the login item: \(error)")
    } catch {}
    switch service.status {
    case .enabled:
        return CommandOutcome(exitCode: 0, message: "Installed. The agent starts now and at every login.")
    case .requiresApproval:
        return approvalNeeded
    default:
        return CommandOutcome(
            exitCode: 1,
            message: "Registered, but the login item is \(describe(service.status))."
        )
    }
}

/// Unregisters the agent, which stops it and removes its login item.
public func uninstallLoginItem(_ service: some LoginItemService) -> CommandOutcome {
    if service.status == .notRegistered || service.status == .notFound {
        return CommandOutcome(exitCode: 0, message: "Not installed. Nothing to remove.")
    }
    do {
        try service.unregister()
    } catch {
        return CommandOutcome(exitCode: 1, message: "Could not unregister the login item: \(error)")
    }
    return CommandOutcome(exitCode: 0, message: "Uninstalled. The agent is stopped and no longer starts at login.")
}

/// Reports the login item's registration state and whether capture is paused.
public func agentStatus(_ service: some LoginItemService, paused: Bool) -> CommandOutcome {
    let capture = paused ? "paused, run `\(AgentIdentity.executableName) resume` to capture again" : "not paused"
    return CommandOutcome(exitCode: 0, message: "Login item: \(describe(service.status)).\nCapture: \(capture).")
}

func describe(_ status: SMAppService.Status) -> String {
    switch status {
    case .enabled: "enabled, starts at login"
    case .requiresApproval: "waiting for approval in System Settings > General > Login Items & Extensions"
    case .notRegistered: "not installed"
    case .notFound: "missing from the app bundle"
    @unknown default: "in an unknown state (\(status.rawValue))"
    }
}
