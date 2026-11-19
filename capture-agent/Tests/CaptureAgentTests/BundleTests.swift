import Foundation
import Testing
@testable import CaptureAgent

func bundlePlist(_ name: String) throws -> [String: Any] {
    let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Bundle").appendingPathComponent(name)
    let plist = try PropertyListSerialization.propertyList(from: Data(contentsOf: url), format: nil)
    return try #require(plist as? [String: Any])
}

@Test func infoPlistMatchesTheAgentIdentity() throws {
    let info = try bundlePlist("Info.plist")
    #expect(info["CFBundleIdentifier"] as? String == AgentIdentity.bundleIdentifier)
    #expect(info["CFBundleExecutable"] as? String == AgentIdentity.executableName)
    #expect(info["LSUIElement"] as? Bool == true)
}

@Test func launchAgentRunsTheBundledBinaryAndKeepsItAlive() throws {
    let agent = try bundlePlist("LaunchAgent.plist")
    #expect(agent["Label"] as? String == AgentIdentity.bundleIdentifier)
    #expect(agent["BundleProgram"] as? String == "Contents/MacOS/\(AgentIdentity.executableName)")
    #expect(agent["KeepAlive"] as? Bool == true)
    #expect(agent["RunAtLoad"] as? Bool == true)
}
