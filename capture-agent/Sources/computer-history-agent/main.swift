import AppKit
import CaptureAgent
import Foundation
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
    let log = AgentLog.unified()
    let spool = SpoolWriter(directory: settings.spoolDirectory, now: Date.init)
    let counts = CaptureCounts()
    let captureStop = CaptureStop()
    exit(AgentLifecycle(
        report: settings.report,
        isPaused: { pause.isPaused },
        accessibilityTrusted: isAccessibilityTrusted(prompt:),
        spool: spool,
        counts: counts,
        startCapturing: {
            startCaptureThread(
                mac: LiveMac(callTimeout: settings.windowText.callTimeout),
                settings: settings,
                spool: spool,
                images: JPEGImageStore(
                    folder: settings.folder, longEdge: settings.screenshots.longEdge, quality: settings.screenshots.quality
                ),
                recognize: recognizeText(inImageAt:),
                counts: counts,
                stop: captureStop,
                log: log
            )
        },
        stopCapturing: captureStop.stop(by:),
        log: log
    ).run())
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
case .requestScreenRecording:
    finish(requestScreenRecording(open: NSWorkspace.shared.open))
case .scriptedSession(let script):
    finish(runScriptedSession(script: URL(fileURLWithPath: script), settings: settings, homes: userHomes(), log: .standardOutput))
case .usage:
    finish(.usage)
}
