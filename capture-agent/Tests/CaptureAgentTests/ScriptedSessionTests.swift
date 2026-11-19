import Foundation
import Testing
@testable import CaptureAgent

func script(_ json: String) throws -> CaptureScript {
    try JSONDecoder().decode(CaptureScript.self, from: Data(json.utf8))
}

let twoApps = """
{
  "start": "2026-11-18T09:00:00.000Z",
  "apps": {
    "notes": {"name": "Notes", "bundle_id": "com.apple.Notes", "focused_window": "a", "windows": {
      "a": {"role": "AXWindow", "title": "A", "children": [{"role": "AXStaticText", "value": "ab", "repeat": 3}]},
      "b": {"role": "AXWindow", "title": "B", "children": [{"role": "AXStaticText", "value": "stuck", "hangs": ["AXValue"]}]}
    }},
    "vault": {"name": "Vault", "bundle_id": "com.1password.1password", "focused_window": "v", "windows": {
      "v": {"role": "AXWindow", "title": "Secret"}
    }}
  },
  "steps": [
    {"at": 0, "focus": "notes"},
    {"at": 5, "focus_window": {"app": "notes", "window": "b"}},
    {"at": 6, "set_title": {"app": "notes", "window": "b", "title": "B2"}},
    {"at": 7, "presence": {"idle_seconds": 500}},
    {"at": 8, "pause": true},
    {"at": 9, "resume": true},
    {"at": 10, "focus": "vault"},
    {"at": 12, "end": true}
  ]
}
"""

func scratchFolder() -> URL {
    FileManager.default.temporaryDirectory.appendingPathComponent("scripted-\(UUID().uuidString)", isDirectory: true)
}

@Test func aScriptPlaysItsStepsOntoTheScriptedMacAsTheyComeDue() throws {
    let mac = ScriptedMac()
    let pause = PauseSwitch(file: scratchFolder().appendingPathComponent("capture-paused"))
    var player = try ScriptPlayer(try script(twoApps), mac: mac, pause: pause)
    #expect(try player.play(upTo: 0))
    let notes = try #require(mac.focused)
    #expect(notes.name == "Notes")
    let window = try #require(mac.applicationElement(notes.processIdentifier).focusedWindow)
    #expect(window.attributes["AXTitle"] == "A")
    #expect(window.children.first?.attributes["AXValue"] == "ababab")
    #expect(try player.play(upTo: 6))
    let switched = try #require(mac.applicationElement(notes.processIdentifier).focusedWindow)
    #expect(switched.attributes["AXTitle"] == "B2")
    #expect(switched.children.first?.hangs == ["AXValue"])
    #expect(try player.play(upTo: 8))
    #expect(mac.presence.idleSeconds == 500)
    #expect(pause.isPaused)
    #expect(try player.play(upTo: 10))
    #expect(!pause.isPaused)
    #expect(mac.focused?.bundleIdentifier == "com.1password.1password")
    #expect(try !player.play(upTo: 12))
    #expect(player.ending == .end)
}

@Test func callCountsAreKeptPerApp() throws {
    let mac = ScriptedMac()
    var player = try ScriptPlayer(try script(twoApps), mac: mac, pause: PauseSwitch(file: scratchFolder()))
    _ = try player.play(upTo: 0)
    _ = mac.applicationElement(mac.focused!.processIdentifier).element("AXFocusedWindow")
    #expect(player.callCounts == ["notes": 1, "vault": 0])
}

@Test(arguments: [
    (#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "focus": "nope"}, {"at": 1, "end": true}]}"#, "no app nope"),
    (#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "pause": true}]}"#, "the last step must be end or crash"),
    (#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 2, "pause": true}, {"at": 1, "end": true}]}"#, "steps must be in time order"),
])
func aScriptThatCannotBePlayedIsRefused(json: String, problem: String) throws {
    #expect(throws: ScriptError(description: problem)) {
        try ScriptPlayer(try script(json), mac: ScriptedMac(), pause: PauseSwitch(file: scratchFolder()))
    }
}

@Test func aScriptWithAnUnknownKeyOrAFalseFlagIsRefused() {
    #expect(throws: DecodingError.self) {
        try script(#"{"start": "2026-11-18T09:00:00.000Z", "apps": {"a": {"name": "A", "windows": {"w": {"role": "AXWindow", "hang": ["AXTitle"]}}}}, "steps": [{"at": 0, "end": true}]}"#)
    }
    #expect(throws: DecodingError.self) {
        try script(#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "presence": {"lock": true}}, {"at": 1, "end": true}]}"#)
    }
    #expect(throws: DecodingError.self) {
        try script(#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "pause": false}, {"at": 1, "end": true}]}"#)
    }
}

@Test func anAppIDWithADotIsRefused() throws {
    let json = #"{"start": "2026-11-18T09:00:00.000Z", "apps": {"com.apple": {"name": "A", "windows": {}}}, "steps": [{"at": 0, "end": true}]}"#
    #expect(throws: ScriptError.self) {
        try ScriptPlayer(try script(json), mac: ScriptedMac(), pause: PauseSwitch(file: scratchFolder()))
    }
}

@Test func aStepNeedsExactlyOneAction() {
    #expect(throws: DecodingError.self) {
        try script(#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "pause": true, "end": true}]}"#)
    }
    #expect(throws: DecodingError.self) {
        try script(#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "focs": "x"}]}"#)
    }
    #expect(throws: DecodingError.self) {
        try script(#"{"start": "2026-11-18T09:00:00.000Z", "apps": {}, "steps": [{"at": 0, "end": true, "extra": 1}]}"#)
    }
}

@Test func theCommittedSessionScriptsLoad() throws {
    let folder = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("e2e")
    for name in ["crash.json", "session.json"] {
        _ = try ScriptPlayer(try CaptureScript.load(folder.appendingPathComponent(name)), mac: ScriptedMac(), pause: PauseSwitch(file: scratchFolder()))
    }
}

@Test func aScriptedSessionRefusesTheRealFolderOrSpool() {
    let home = scratchFolder()
    let real = AgentSettings.defaultFolder(home: home)
    let scratch = scratchFolder()
    let cases: [(AgentSettings, Bool)] = [
        (AgentSettings(folder: scratch, spoolDirectory: scratch.appendingPathComponent("spool")), false),
        (AgentSettings(folder: real, spoolDirectory: scratch), true),
        (AgentSettings(folder: scratch, spoolDirectory: real.appendingPathComponent("spool")), true),
        (AgentSettings(folder: real.appendingPathComponent("nested/deeper"), spoolDirectory: scratch), true),
    ]
    for (settings, refused) in cases {
        #expect((scriptedSessionRefusal(settings, homes: [scratch, home]) != nil) == refused)
    }
}

@Test func aScriptedSessionRefusesAFolderReachedThroughALink() throws {
    let home = scratchFolder()
    let real = AgentSettings.defaultFolder(home: home)
    try FileManager.default.createDirectory(at: real, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: home) }
    let link = home.appendingPathComponent("link")
    try FileManager.default.createSymbolicLink(at: link, withDestinationURL: real)
    let settings = AgentSettings(folder: link.appendingPathComponent("not-yet"), spoolDirectory: scratchFolder())
    #expect(scriptedSessionRefusal(settings, homes: [home]) != nil)
}

@Test func aScriptedSessionRefusesAFolderThatHoldsADatabase() throws {
    let folder = scratchFolder()
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: folder) }
    let settings = AgentSettings(folder: folder, spoolDirectory: folder.appendingPathComponent("spool"))
    #expect(scriptedSessionRefusal(settings, homes: [scratchFolder()]) == nil)
    try Data().write(to: folder.appendingPathComponent("history.db"))
    #expect(scriptedSessionRefusal(settings, homes: [scratchFolder()])?.contains("already holds a database (history.db)") == true)
}

@Test func aRefusedScriptedSessionWritesNothing() throws {
    let home = scratchFolder()
    let settings = AgentSettings(folder: AgentSettings.defaultFolder(home: home), spoolDirectory: scratchFolder())
    let outcome = runScriptedSession(script: URL(fileURLWithPath: "/nonexistent.json"), settings: settings, homes: [home], log: { _ in })
    #expect(outcome.exitCode == 1)
    #expect(outcome.message.hasPrefix("refusing a scripted session"))
    #expect(!FileManager.default.fileExists(atPath: settings.spoolDirectory.path))
}
