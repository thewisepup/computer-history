import Foundation
import Testing
@testable import CaptureAgent

@Test func firstPollAndAnUnchangedFocusReportNothing() {
    let fixture = FocusFixture()
    var watch = fixture.watch()
    #expect(watch.poll() == nil)
    #expect(watch.poll() == nil)
    #expect(watch.application == plainApp)
}

@Test func reportsAnAppSwitch() {
    let fixture = FocusFixture()
    var watch = fixture.watch()
    _ = watch.poll()
    fixture.focused = chrome
    #expect(watch.poll() == .app)
    #expect(watch.application == chrome)
    #expect(watch.poll() == nil)
}

@Test func reportsAWindowSwitchWithinAnApp() {
    let fixture = FocusFixture()
    var watch = fixture.watch()
    _ = watch.poll()
    fixture.apps[plainApp.processIdentifier]!.focusedWindow = fixture.tree.window("Notes", children: [])
    #expect(watch.poll() == .window)
    fixture.apps[plainApp.processIdentifier]!.focusedWindow = nil
    #expect(watch.poll() == .window)
}

@Test func reportsATabOrFileSwitchAsATitleChange() {
    let fixture = FocusFixture()
    fixture.focused = chrome
    var watch = fixture.watch()
    _ = watch.poll()
    fixture.tab.attributes["AXTitle"] = "Pull requests"
    #expect(watch.poll() == .title)
    #expect(watch.poll() == nil)
}

@Test func aTimedOutReadIsNotAChange() {
    let fixture = FocusFixture()
    var watch = fixture.watch()
    _ = watch.poll()
    fixture.notes.hangs = ["AXTitle"]
    #expect(watch.poll() == nil)
    fixture.notes.hangs = []
    #expect(watch.poll() == nil)
    let app = fixture.apps[plainApp.processIdentifier]!
    app.hangs = ["AXFocusedWindow"]
    #expect(watch.poll() == nil)
    app.hangs = []
    #expect(watch.poll() == nil)
}

@Test func anUnknownFocusedAppIsNotCapturedButStillCountsAsTheLastOne() {
    let fixture = FocusFixture()
    var watch = fixture.watch()
    _ = watch.poll()
    fixture.focused = nil
    #expect(watch.poll() == nil)
    #expect(watch.application == nil)
    fixture.focused = plainApp
    #expect(watch.poll() == nil)
    fixture.focused = chrome
    #expect(watch.poll() == .app)
}

@Test func aWindowThatTimedOutDuringAnAppSwitchCountsOnceItIsRead() {
    let fixture = FocusFixture()
    var watch = fixture.watch()
    _ = watch.poll()
    let browser = fixture.apps[chrome.processIdentifier]!
    browser.hangs = ["AXFocusedWindow"]
    fixture.focused = chrome
    #expect(watch.poll() == .app)
    browser.hangs = []
    #expect(watch.poll() == .window)
    #expect(watch.poll() == nil)
}
