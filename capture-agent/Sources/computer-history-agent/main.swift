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
let settings = AgentSettings.load()
let pause = settings.pause

switch AgentCommand(arguments: Array(CommandLine.arguments.dropFirst())) {
case .run:
    let logger = Logger(subsystem: AgentIdentity.bundleIdentifier, category: "agent")
    let log: @Sendable (String) -> Void = { logger.notice("\($0, privacy: .public)") }
    let spool = SpoolWriter(directory: settings.spoolDirectory, now: Date.init)
    let counts = CaptureCounts()
    AgentLoop(
        report: settings.report,
        isPaused: { pause.isPaused },
        accessibilityTrusted: isAccessibilityTrusted(prompt:),
        spool: spool,
        counts: counts,
        startCapturing: {
            startCaptureThread(
                mac: LiveMac(callTimeout: settings.windowText.callTimeout), settings: settings, spool: spool, counts: counts, log: log
            )
        },
        log: log
    ).run()
case .install:
    finish(installLoginItem(loginItem))
case .uninstall:
    finish(uninstallLoginItem(loginItem))
case .status:
    finish(agentStatus(loginItem, paused: pause.isPaused))
case .pause:
    finish(pauseCapture(pause))
case .resume:
    finish(resumeCapture(pause))
case .checkConfig:
    finish(checkConfig(settings))
case .scriptedSession(let script):
    finish(runScriptedSession(script: URL(fileURLWithPath: script), settings: settings, homes: userHomes(), log: { print($0) }))
case .usage:
    finish(.usage)
}
