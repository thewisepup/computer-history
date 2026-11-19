import Testing
@testable import CaptureAgent

@Test(arguments: [
    ([], AgentCommand.run),
    (["run"], .run),
    (["install"], .install),
    (["uninstall"], .uninstall),
    (["status"], .status),
    (["pause"], .pause),
    (["resume"], .resume),
    (["check-config"], .checkConfig),
    (["pause", "now"], .usage),
    (["install", "now"], .usage),
    (["--help"], .usage),
])
func parsesCommandLine(arguments: [String], expected: AgentCommand) {
    #expect(AgentCommand(arguments: arguments) == expected)
}
