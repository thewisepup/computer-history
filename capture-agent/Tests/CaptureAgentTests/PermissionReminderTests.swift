import Foundation
import Testing
@testable import CaptureAgent

private let day: TimeInterval = 24 * 60 * 60

private func missingGrant(_ fixture: LoopFixture) {
    fixture.mac.windowImage = { _, _ in .noPermission }
}

private func grantHeld(_ fixture: LoopFixture) {
    fixture.mac.windowImage = { _, _ in .image(fixtureImage(width: 1600, height: 1000), windowID: 1) }
}

private func later(_ seconds: TimeInterval, _ fixture: LoopFixture) {
    fixture.mac.clock += seconds
    fixture.run(for: 2)
}

@Test func theFirstMissingGrantPostsOneReminderThatOpensTheScreenRecordingSettings() throws {
    let fixture = LoopFixture()
    missingGrant(fixture)
    fixture.run(for: 120)
    try #require(fixture.mac.notifications.count == 1)
    #expect(fixture.mac.notifications[0].opens == ScreenRecordingSettings.links)
    #expect(fixture.mac.notifications[0].title.contains("screenshots"))
    #expect(try fixture.screenshotRecords().count > 1)
    #expect(fixture.logged.filter { $0.contains("reminder") } == ["screen recording missing, posted a reminder"])
}

@Test func theReminderRepeatsOnlyAfterADayWhileTheGrantIsStillMissing() throws {
    let fixture = LoopFixture()
    missingGrant(fixture)
    fixture.run(for: 2)
    later(day - 60, fixture)
    #expect(fixture.mac.notifications.count == 1)
    later(60, fixture)
    #expect(fixture.mac.notifications.count == 2)
    later(60, fixture)
    #expect(fixture.mac.notifications.count == 2)
}

@Test func aRestartKeepsTheDayBetweenReminders() throws {
    let fixture = LoopFixture()
    missingGrant(fixture)
    fixture.run(for: 2)
    fixture.restart()
    later(day / 2, fixture)
    #expect(fixture.mac.notifications.count == 1)
    fixture.restart()
    later(day / 2, fixture)
    #expect(fixture.mac.notifications.count == 2)
}

@Test func aScreenshotTakenClearsTheReminderSoALaterLossRemindsAtOnce() throws {
    let fixture = LoopFixture()
    missingGrant(fixture)
    fixture.run(for: 2)
    grantHeld(fixture)
    later(60, fixture)
    #expect(try fixture.screenshotRecords().last?["status"] as? String == "kept")
    fixture.restart()
    missingGrant(fixture)
    later(60, fixture)
    #expect(fixture.mac.notifications.count == 2)
}

@Test func unavailableNotificationsAreLoggedOnceAndNothingElseHappens() throws {
    let fixture = LoopFixture()
    fixture.mac.notificationPosting = .unavailable("notifications are off for the agent")
    missingGrant(fixture)
    fixture.run(for: 2)
    later(day, fixture)
    later(day, fixture)
    #expect(fixture.mac.notifications.count == 3)
    #expect(fixture.logged.filter { $0.contains("notifications") } == [
        "screen recording missing, notifications unavailable (notifications are off for the agent), status is the only warning",
    ])
    #expect(try fixture.screenshotRecords().allSatisfy { $0["status"] as? String == "no-permission" })
}

private func reminders(at offsets: [TimeInterval], of rule: inout PermissionReminder, from start: Date) -> [Bool] {
    offsets.map { rule.remindNow(at: start.addingTimeInterval($0)) }
}

private func reminderFile() -> URL {
    FileManager.default.temporaryDirectory
        .appendingPathComponent("reminder-\(UUID().uuidString)")
        .appendingPathComponent(AgentSettings.permissionReminderFileName)
}

@Test func theRuleRemindsOnceADayAndForgetsWhenTheGrantIsSeen() throws {
    let file = reminderFile()
    defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
    let start = Date(timeIntervalSince1970: 1_000_000)
    var rule = PermissionReminder(file: file)
    #expect(reminders(at: [0, day - 1], of: &rule, from: start) == [true, false])
    var restarted = PermissionReminder(file: file)
    #expect(reminders(at: [day - 1, day], of: &restarted, from: start) == [false, true])
    restarted.grantSeen()
    #expect(!FileManager.default.fileExists(atPath: file.path))
    #expect(reminders(at: [day + 1], of: &restarted, from: start) == [true])
}

@Test func aClockSetBackOrAnUnreadableFileRemindsAgain() throws {
    let file = reminderFile()
    defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
    let start = Date(timeIntervalSince1970: 1_000_000)
    var rule = PermissionReminder(file: file)
    #expect(reminders(at: [0, -60], of: &rule, from: start) == [true, true])
    try Data("not a time".utf8).write(to: file)
    var reread = PermissionReminder(file: file)
    #expect(reminders(at: [0], of: &reread, from: start) == [true])
}

@Test func clickingOpensTheFirstSettingsLinkThatOpens() {
    var tried: [URL] = []
    let opened = ScreenRecordingSettings.open { tried.append($0); return tried.count == 2 }
    #expect(tried == ScreenRecordingSettings.links)
    #expect(opened == ScreenRecordingSettings.links[1])
    #expect(ScreenRecordingSettings.links[0].absoluteString
        == "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture")
    #expect(ScreenRecordingSettings.open { _ in false } == nil)
}

@Test func theInstallRequestAsksForTheGrantAndOpensTheSettingsOnce() {
    var asked = 0
    var opened: [URL] = []
    let outcome = requestScreenRecording(request: { asked += 1; return false }, open: { opened.append($0); return true })
    #expect(asked == 1)
    #expect(opened == [ScreenRecordingSettings.links[0]])
    #expect(outcome.exitCode == 0)
    #expect(outcome.message.contains("Screen Recording"))
    let failed = requestScreenRecording(request: { true }, open: { _ in false })
    #expect(failed.exitCode == 1)
}
