import Foundation
import Testing
@testable import CaptureAgent

private let day = PermissionReminder.interval

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

private func reminderLines(_ fixture: LoopFixture) -> [String] {
    fixture.logged.filter { $0.hasPrefix("screen recording missing") }
}

@Test func theFirstMissingGrantPostsOneReminderThatOpensTheScreenRecordingSettings() throws {
    let fixture = LoopFixture()
    missingGrant(fixture)
    fixture.run(for: 120)
    try #require(fixture.mac.notifications.count == 1)
    #expect(fixture.mac.notifications[0].opens == ScreenRecordingSettings.links)
    #expect(fixture.mac.notifications[0].title.contains("screenshots"))
    #expect(try fixture.screenshotRecords().count > 1)
    #expect(reminderLines(fixture) == ["screen recording missing, posted a reminder"])
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
    fixture.run(for: 120)
    later(day, fixture)
    later(day, fixture)
    #expect(fixture.mac.notifications.count == 3)
    #expect(reminderLines(fixture) == [
        "screen recording missing, notifications unavailable (notifications are off for the agent), status is the only warning",
    ])
    #expect(try fixture.screenshotRecords().allSatisfy { $0["status"] as? String == "no-permission" })
}

@Test func aReminderNotShownStartsNoDayAcrossARestart() throws {
    let fixture = LoopFixture()
    fixture.mac.notificationPosting = .awaitingPermission
    missingGrant(fixture)
    fixture.run(for: 120)
    #expect(fixture.mac.notifications.count == 1)
    #expect(!FileManager.default.fileExists(atPath: fixture.settings.permissionReminderFile.path))
    fixture.mac.notificationPosting = .posted
    fixture.restart()
    later(60, fixture)
    #expect(fixture.mac.notifications.count == 2)
    #expect(reminderLines(fixture) == [
        "screen recording missing, asked macOS to allow notifications for the reminder",
        "screen recording missing, posted a reminder",
    ])
}

@Test func aSlowNotificationCentreIsLoggedAsATimeoutAndALaterUnavailableIsStillLogged() throws {
    let fixture = LoopFixture()
    fixture.mac.notificationPosting = .timedOut(2)
    missingGrant(fixture)
    fixture.run(for: 120)
    fixture.mac.notificationPosting = .unavailable("notifications are off for the agent")
    later(day, fixture)
    #expect(fixture.mac.notifications.count == 2)
    #expect(reminderLines(fixture) == [
        "screen recording missing, the notification centre did not answer within 2s",
        "screen recording missing, notifications unavailable (notifications are off for the agent), status is the only warning",
    ])
}

@Test func aReminderTimeThatCannotBeSavedIsLoggedOnce() throws {
    let fixture = LoopFixture()
    try FileManager.default.createDirectory(at: fixture.settings.permissionReminderFile, withIntermediateDirectories: true)
    missingGrant(fixture)
    fixture.run(for: 2)
    later(day, fixture)
    #expect(fixture.mac.notifications.count == 2)
    #expect(fixture.logged.filter { $0.contains("could not save") }.count == 1)
    #expect(fixture.logged.contains { $0.hasPrefix("could not save the reminder time to \(fixture.settings.permissionReminderFile.path)") })
}

private func reminderFile() -> URL {
    FileManager.default.temporaryDirectory
        .appendingPathComponent("reminder-\(UUID().uuidString)")
        .appendingPathComponent(AgentSettings.permissionReminderFileName)
}

private func posts(at offsets: [TimeInterval], of reminder: inout PermissionReminder, from start: Date) -> [Bool] {
    offsets.map { offset in
        var posted = false
        reminder.grantMissing(at: start.addingTimeInterval(offset), post: { _ in posted = true; return .posted }, log: { _ in })
        return posted
    }
}

@Test func theRulePostsOnceADayAndForgetsWhenTheGrantIsSeen() throws {
    let file = reminderFile()
    defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
    let start = Date(timeIntervalSince1970: 1_000_000)
    var reminder = PermissionReminder(file: file)
    #expect(posts(at: [0, day - 1], of: &reminder, from: start) == [true, false])
    var restarted = PermissionReminder(file: file)
    #expect(posts(at: [day - 1, day], of: &restarted, from: start) == [false, true])
    restarted.grantSeen()
    #expect(!FileManager.default.fileExists(atPath: file.path))
    #expect(posts(at: [day + 1], of: &restarted, from: start) == [true])
}

@Test func aClockSetBackWaitsOutTheDayUnlessTheSavedTimeIsMoreThanADayAhead() throws {
    let file = reminderFile()
    defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
    let start = Date(timeIntervalSince1970: 1_000_000)
    var reminder = PermissionReminder(file: file)
    #expect(posts(at: [0, -3_600 + 600, -day + 1, -day - 1], of: &reminder, from: start) == [true, false, false, true])
    try Data("not a time".utf8).write(to: file)
    var reread = PermissionReminder(file: file)
    #expect(posts(at: [0], of: &reread, from: start) == [true])
}

@Test func clickingTheReminderOpensTheFirstSettingsLinkThatOpens() {
    let clicked = LiveNotifications.userInfo(for: ScreenRecordingSettings.reminder)
    var tried: [URL] = []
    let opened = LiveNotifications.openLinks(in: clicked) { tried.append($0); return tried.count == 2 }
    #expect(tried == ScreenRecordingSettings.links)
    #expect(opened == ScreenRecordingSettings.links[1])
    #expect(ScreenRecordingSettings.links[0].absoluteString
        == "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture")
    #expect(LiveNotifications.openLinks(in: clicked) { _ in false } == nil)
}

@Test func theInstallRequestAsksForTheGrantAndOpensTheSettingsOnlyWhenItIsMissing() {
    var asked = 0
    var opened: [URL] = []
    let outcome = requestScreenRecording(request: { asked += 1; return false }, open: { opened.append($0); return true })
    #expect(asked == 1)
    #expect(opened == [ScreenRecordingSettings.links[0]])
    #expect(outcome.exitCode == 0)
    #expect(outcome.message.contains("Screen Recording"))
    #expect(requestScreenRecording(request: { false }, open: { _ in false }).exitCode == 1)
    opened = []
    let held = requestScreenRecording(request: { true }, open: { opened.append($0); return true })
    #expect(held.exitCode == 0)
    #expect(opened.isEmpty)
}
