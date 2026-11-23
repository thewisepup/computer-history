import Foundation

/// Plays a capture script through the real capture loop and spool writer on a virtual clock, finishing the spool at the end unless the script ends in a crash.
public func runScriptedSession(
    script file: URL,
    settings: AgentSettings,
    homes: [URL],
    log: AgentLog
) -> CommandOutcome {
    if let refusal = scriptedSessionRefusal(settings, homes: homes) {
        return CommandOutcome(exitCode: 1, message: refusal)
    }
    let mac: ScriptedMac
    var player: ScriptPlayer
    do {
        let script = try CaptureScript.load(file)
        mac = ScriptedMac(start: script.start)
        mac.callTimeout = settings.windowText.callTimeout
        player = try ScriptPlayer(script, mac: mac, pause: settings.pause)
    } catch {
        return CommandOutcome(exitCode: 1, message: "cannot play \(file.path): \(error)")
    }
    let spool = SpoolWriter(directory: settings.spoolDirectory, now: { mac.now() })
    let counts = CaptureCounts()
    let pause = settings.pause
    let agent = AgentLifecycle(
        report: settings.report,
        instanceLock: nil,
        isPaused: { pause.isPaused },
        accessibilityTrusted: { _ in mac.accessibilityTrusted() },
        spool: spool,
        counts: counts,
        startCapturing: {},
        stopCapturing: { _ in 0 },
        log: log
    )
    guard agent.start() == .started else {
        return CommandOutcome(exitCode: 1, message: "another agent is writing to \(spool.directory.path)")
    }
    let images = ScriptedImageStore(
        images: JPEGImageStore(folder: settings.folder, longEdge: settings.screenshots.longEdge, quality: settings.screenshots.quality),
        mac: mac,
        texts: player.recognizedTexts
    )
    let loop = CaptureLoop(
        settings: settings, mac: mac, spool: spool, images: images, recognize: images.recognizedText(inImageAt:), counts: counts, log: log
    )
    var nextFinish = AgentLifecycle.spoolFinishInterval
    var failure: (any Error)?
    loop.run {
        if mac.clock >= nextFinish {
            agent.finishSpoolFile()
            nextFinish += AgentLifecycle.spoolFinishInterval
        }
        do {
            return try player.play(upTo: mac.clock)
        } catch {
            failure = error
            return false
        }
    }
    loop.stopRecordingSleep()
    loop.waitForScreenshots()
    if let failure {
        return CommandOutcome(exitCode: 1, message: "the script failed at \(mac.clock)s: \(failure)")
    }
    let calls = player.callCounts.sorted { $0.key < $1.key }.map { "\($0.key) \($0.value)" }.joined(separator: ", ")
    let summary = "\(counts.take())\naccessibility calls: \(calls)"
    if player.ending == .crash {
        return CommandOutcome(
            exitCode: 0,
            message: "crashed at \(mac.clock)s, leaving \(SpoolWriter.openFileName) unfinished: \(summary)"
        )
    }
    agent.finishSpoolFile()
    return CommandOutcome(exitCode: 0, message: "ended at \(mac.clock)s: \(summary)")
}
