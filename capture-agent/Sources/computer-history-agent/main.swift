import CaptureAgent
import Foundation
import os
import ServiceManagement

func finish(_ outcome: CommandOutcome) -> Never {
    if outcome.exitCode == 0 {
        print(outcome.message)
    } else {
        FileHandle.standardError.write(Data((outcome.message + "\n").utf8))
    }
    exit(outcome.exitCode)
}

let loginItem = SMAppService.agent(plistName: AgentIdentity.launchAgentPlistName)

switch AgentCommand(arguments: Array(CommandLine.arguments.dropFirst())) {
case .run:
    let logger = Logger(subsystem: AgentIdentity.bundleIdentifier, category: "agent")
    let log: @Sendable (String) -> Void = { logger.notice("\($0, privacy: .public)") }
    let spool = SpoolWriter(directory: SpoolWriter.defaultDirectory, now: Date.init)
    let counts = CaptureCounts()
    AgentLoop(
        accessibilityTrusted: isAccessibilityTrusted(prompt:),
        spool: spool,
        counts: counts,
        startCapturing: {
            startCaptureThread(
                settings: CaptureSettings(), windowText: WindowTextSettings(), spool: spool, counts: counts, log: log
            )
        },
        log: log
    ).run()
case .install:
    finish(installLoginItem(loginItem))
case .uninstall:
    finish(uninstallLoginItem(loginItem))
case .status:
    finish(loginItemStatus(loginItem))
case .usage:
    finish(.usage)
}
