import Foundation
import Testing
@testable import CaptureAgent

@Test func firstPollAndAnUnchangedAppReportNothing() {
    let fixture = FocusFixture()
    var apps = fixture.appWatch
    #expect(apps.poll() == nil)
    #expect(apps.poll() == nil)
    #expect(apps.application == plainApp)
}

@Test func reportsAnAppSwitch() {
    let fixture = FocusFixture()
    var apps = fixture.appWatch
    _ = apps.poll()
    fixture.mac.focused = chrome
    #expect(apps.poll() == .app)
    #expect(apps.application == chrome)
    #expect(apps.poll() == nil)
}

@Test func anUnknownFocusedAppIsNotReportedButTheLastOneStillCounts() {
    let fixture = FocusFixture()
    var apps = fixture.appWatch
    _ = apps.poll()
    fixture.mac.focused = nil
    #expect(apps.poll() == nil)
    #expect(apps.application == nil)
    fixture.mac.focused = plainApp
    #expect(apps.poll() == nil)
    fixture.mac.focused = chrome
    #expect(apps.poll() == .app)
}

@Test func watchingTheFocusedAppMakesNoAccessibilityCalls() {
    let fixture = FocusFixture()
    var apps = fixture.appWatch
    _ = apps.poll()
    fixture.mac.focused = chrome
    _ = apps.poll()
    #expect(fixture.mac.calls.isEmpty)
}

@Test func firstWindowPollAndAnUnchangedWindowReportNothing() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    #expect(windows.poll(plainApp) == nil)
    #expect(windows.poll(plainApp) == nil)
}

@Test func theFirstWindowPollOfANewlyFocusedAppIsNotAChange() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    _ = windows.poll(plainApp)
    #expect(windows.poll(chrome) == nil)
    #expect(windows.poll(chrome) == nil)
}

@Test func reportsAWindowSwitchWithinAnApp() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    _ = windows.poll(plainApp)
    fixture.mac.apps[plainApp.processIdentifier]!.focusedWindow = fixture.mac.window("Notes", children: [])
    #expect(windows.poll(plainApp) == .window)
    fixture.mac.apps[plainApp.processIdentifier]!.focusedWindow = nil
    #expect(windows.poll(plainApp) == .window)
}

@Test func reportsATabOrFileSwitchAsATitleChange() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    _ = windows.poll(chrome)
    fixture.tab.attributes["AXTitle"] = "Pull requests"
    #expect(windows.poll(chrome) == .title)
    #expect(windows.poll(chrome) == nil)
}

@Test func aTimedOutReadIsNotAChange() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    _ = windows.poll(plainApp)
    fixture.notes.hangs = ["AXTitle"]
    #expect(windows.poll(plainApp) == nil)
    fixture.notes.hangs = []
    #expect(windows.poll(plainApp) == nil)
    let app = fixture.mac.apps[plainApp.processIdentifier]!
    app.hangs = ["AXFocusedWindow"]
    #expect(windows.poll(plainApp) == nil)
    app.hangs = []
    #expect(windows.poll(plainApp) == nil)
}

@Test func aWindowThatTimedOutOnAnAppSwitchCountsOnceItIsRead() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    _ = windows.poll(plainApp)
    let browser = fixture.mac.apps[chrome.processIdentifier]!
    browser.hangs = ["AXFocusedWindow"]
    #expect(windows.poll(chrome) == nil)
    browser.hangs = []
    #expect(windows.poll(chrome) == .window)
    #expect(windows.poll(chrome) == nil)
}

@Test func forgettingStartsTheNextPollAfresh() {
    let fixture = FocusFixture()
    var windows = fixture.windowWatch
    _ = windows.poll(plainApp)
    windows.forget()
    fixture.notes.attributes["AXTitle"] = "Renamed"
    #expect(windows.poll(plainApp) == nil)
}
