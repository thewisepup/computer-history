import Foundation
import Testing
@testable import CaptureAgent

func readOnce(_ mac: ScriptedMac, _ window: ScriptedElement?, settings: WindowTextSettings = WindowTextSettings()) -> WindowText {
    mac.reader([plainApp.processIdentifier: mac.app(window: window)], settings: settings).read(plainApp)
}

@Test func keepsContentRolesAndDropsControlsAndContainers() {
    let mac = ScriptedMac()
    let window = mac.window("Notes", children: [
        mac.node("group", role: "AXGroup", ["AXTitle": "group title", "AXDescription": "group description"], children: [
            mac.text("static"),
            mac.node("area", role: "AXTextArea", ["AXValue": "area"]),
            mac.node("field", role: "AXTextField", ["AXValue": "field", "AXDescription": "Search"]),
            mac.node("heading", role: "AXHeading", ["AXTitle": "heading", "AXValue": "2"]),
            mac.node("link", role: "AXLink", ["AXTitle": "link"]),
        ]),
        mac.node("button", role: "AXButton", ["AXTitle": "OK"], children: [mac.text("button label")]),
        mac.node("popup", role: "AXPopUpButton", ["AXValue": "Choice"]),
        mac.node("checkbox", role: "AXCheckBox", ["AXTitle": "Remember"]),
        mac.node("radio", role: "AXRadioButton", ["AXTitle": "Option"]),
        mac.node("row", role: "AXRow", ["AXDescription": "row description"]),
        mac.node("image", role: "AXImage", ["AXDescription": "logo"]),
    ])
    let result = readOnce(mac, window)
    #expect(result.title == "Notes")
    #expect(result.text == "static\narea\nfield\nheading\nlink")
    #expect(result.fullLength == result.text.utf8.count)
    #expect(!result.timedOut)
    #expect(mac.reads(of: "button") == ["button.AXRole", "button.AXSubrole"])
}

@Test func descendsThroughNestedContainers() {
    let mac = ScriptedMac()
    let window = mac.window("Deep", children: [
        mac.node("outer", role: "AXGroup", children: [
            mac.node("table", role: "AXTable", children: [
                mac.node("row", role: "AXRow", children: [
                    mac.node("cell", role: "AXCell", children: [mac.text("deep text")]),
                ]),
            ]),
            mac.node("unknown", role: "AXUnknown", children: [mac.text("more")]),
        ]),
    ])
    #expect(readOnce(mac, window).text == "deep text\nmore")
}

@Test func neverReadsSecureFieldsOrTheirChildren() {
    let mac = ScriptedMac()
    let byRole = mac.node("secureRole", role: "AXSecureTextField", ["AXValue": "hunter2"], children: [mac.text("role child")])
    let bySubrole = mac.node(
        "secureSubrole",
        role: "AXTextField",
        ["AXSubrole": "AXSecureTextField", "AXValue": "hunter3"],
        children: [mac.text("subrole child")]
    )
    let window = mac.window("Sign in", children: [mac.text("Password"), byRole, bySubrole])
    let result = readOnce(mac, window)
    #expect(result.text == "Password")
    #expect(mac.reads(of: "secureRole") == ["secureRole.AXRole"])
    #expect(mac.reads(of: "secureSubrole") == ["secureSubrole.AXRole", "secureSubrole.AXSubrole"])
}

@Test func doesNotRepeatTextAParentSharesWithItsChildren() {
    let mac = ScriptedMac()
    let window = mac.window("Docs", children: [
        mac.node("link", role: "AXLink", ["AXTitle": "Home", "AXDescription": "Home"], children: [mac.text("Home")]),
        mac.node("heading", role: "AXHeading", ["AXTitle": "Intro", "AXValue": "1"], children: [mac.text("Intro")]),
        mac.node("area", role: "AXTextArea", ["AXValue": "draft body"], children: [mac.text("draft body")]),
        mac.node("iconLink", role: "AXLink", ["AXDescription": "Close tab"], children: [
            mac.node("icon", role: "AXImage", ["AXDescription": "x"]),
        ]),
    ])
    #expect(readOnce(mac, window).text == "Home\nIntro\ndraft body\nClose tab")
}

@Test func emptyTextAreaDescendsIntoItsChildren() {
    let mac = ScriptedMac()
    let window = mac.window("Editor", children: [
        mac.node("area", role: "AXTextArea", ["AXValue": ""], children: [mac.text("line one"), mac.text("line two")]),
    ])
    #expect(readOnce(mac, window).text == "line one\nline two")
}

@Test func capsTextAndKeepsCountingTheFullLength() {
    let mac = ScriptedMac()
    let window = mac.window("Long", children: [mac.text("abcdef"), mac.text("ghij"), mac.text("klmno")])
    let result = readOnce(mac, window, settings: WindowTextSettings(textCapBytes: 9))
    #expect(result.text == "abcdef\ngh")
    #expect(result.fullLength == "abcdef\nghij\nklmno".utf8.count)
    #expect(!result.timedOut)
}

@Test func perCallTimeoutKeepsTheTextSoFarAndStops() {
    let mac = ScriptedMac()
    let stuck = mac.text("never read")
    stuck.hangs = ["AXValue"]
    let window = mac.window("Busy", children: [mac.text("before"), stuck, mac.text("after")])
    let result = readOnce(mac, window)
    #expect(result.text == "before")
    #expect(result.timedOut)
    #expect(mac.reads(of: "after").isEmpty)
}

@Test func hungAppCostsOneCallTimeout() {
    let mac = ScriptedMac()
    let app = mac.app(window: mac.window("Hung", children: [mac.text("unreachable")]))
    app.hangs = ["AXFocusedWindow"]
    let result = mac.reader([plainApp.processIdentifier: app]).read(plainApp)
    #expect(result.timedOut)
    #expect(result.text.isEmpty)
    #expect(result.title == nil)
    #expect(mac.calls == ["app.AXFocusedWindow"])
    #expect(mac.clock == mac.callTimeout)
}

@Test func windowTimeoutStopsWithinTheBudgetPlusOneCall() {
    let mac = ScriptedMac()
    mac.callCost = 0.01
    let window = mac.window("Huge", children: (0..<1_000).map { mac.text("line \($0)") })
    let settings = WindowTextSettings()
    let result = readOnce(mac, window, settings: settings)
    #expect(result.timedOut)
    #expect(!result.text.isEmpty)
    #expect(result.text.hasPrefix("line 0\nline 1\n"))
    #expect(!result.text.contains("line 999"))
    #expect(mac.clock <= settings.windowTimeout + mac.callCost + 1e-9)
}

@Test func windowTimeoutAfterTheCapLeavesAPartialFullLength() {
    let mac = ScriptedMac()
    mac.callCost = 0.01
    let window = mac.window("Huge", children: (0..<1_000).map { _ in mac.text("0123456789") })
    let result = readOnce(mac, window, settings: WindowTextSettings(textCapBytes: 20))
    #expect(result.timedOut)
    #expect(result.text.utf8.count == 20)
    #expect(result.fullLength > 20)
    #expect(result.fullLength < 1_000 * 11)
}

@Test func setsTheFlagOncePerChromiumProcess() {
    let mac = ScriptedMac()
    let first = mac.app(window: mac.window("Tab", children: []))
    let relaunched = mac.app(window: mac.window("Tab", children: []))
    let reader = mac.reader([200: first, 201: relaunched])
    _ = reader.read(chrome)
    _ = reader.read(chrome)
    let other = FocusedApplication(processIdentifier: 201, bundleIdentifier: chrome.bundleIdentifier, bundleURL: chrome.bundleURL, name: chrome.name)
    _ = reader.read(other)
    #expect(first.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
    #expect(relaunched.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
}

@Test func setsTheFlagAgainWhenAProcessIDIsReusedByAnotherLaunch() {
    let mac = ScriptedMac()
    let elements = (0..<3).map { _ in mac.app(window: mac.window("Tab", children: [])) }
    var current = elements[0]
    let reader = WindowTextReader(
        settings: WindowTextSettings(), applicationElement: { _ in current }, hasElectronFramework: { _ in true }, now: { mac.clock }
    )
    let launched = FocusedApplication(
        processIdentifier: 200, bundleIdentifier: chrome.bundleIdentifier, bundleURL: chrome.bundleURL, name: chrome.name,
        launchDate: Date(timeIntervalSince1970: 1)
    )
    let relaunched = FocusedApplication(
        processIdentifier: 200, bundleIdentifier: chrome.bundleIdentifier, bundleURL: chrome.bundleURL, name: chrome.name,
        launchDate: Date(timeIntervalSince1970: 2)
    )
    let otherApp = FocusedApplication(
        processIdentifier: 200, bundleIdentifier: cursor.bundleIdentifier, bundleURL: cursor.bundleURL, name: cursor.name,
        launchDate: Date(timeIntervalSince1970: 2)
    )
    _ = reader.read(launched)
    _ = reader.read(launched)
    current = elements[1]
    _ = reader.read(relaunched)
    current = elements[2]
    _ = reader.read(otherApp)
    #expect(elements.map(\.flagsSet) == Array(repeating: ["AXManualAccessibility", "AXEnhancedUserInterface"], count: 3))
}

@Test func setsTheFlagOnElectronApps() {
    let mac = ScriptedMac()
    let app = mac.app(window: nil)
    let reader = mac.reader([cursor.processIdentifier: app], electronBundles: ["/Applications/Cursor.app"])
    _ = reader.read(cursor)
    #expect(app.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
}

@Test func skipsTheFlagForOffListAndOtherApps() {
    let mac = ScriptedMac()
    let chromeApp = mac.app(window: nil)
    let plain = mac.app(window: nil)
    let electron = mac.app(window: nil)
    let reader = mac.reader(
        [chrome.processIdentifier: chromeApp, plainApp.processIdentifier: plain, cursor.processIdentifier: electron],
        settings: WindowTextSettings(flagOffList: [chrome.bundleIdentifier!, cursor.bundleIdentifier!]),
        electronBundles: ["/Applications/Cursor.app"]
    )
    _ = reader.read(chrome)
    _ = reader.read(plainApp)
    _ = reader.read(cursor)
    #expect(chromeApp.flagsSet.isEmpty)
    #expect(plain.flagsSet.isEmpty)
    #expect(electron.flagsSet.isEmpty)
}

@Test func retriesTheFlagAfterItTimesOut() {
    let mac = ScriptedMac()
    let app = mac.app(window: mac.window("Tab", children: [mac.text("page")]))
    app.hangs = ["AXManualAccessibility"]
    let reader = mac.reader([chrome.processIdentifier: app])
    let slow = reader.read(chrome)
    #expect(!slow.timedOut)
    #expect(slow.text == "page")
    #expect(app.flagsSet.isEmpty)
    app.hangs = []
    let recovered = reader.read(chrome)
    #expect(!recovered.timedOut)
    #expect(recovered.text == "page")
    #expect(app.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
}

@Test func hungChromiumAppStaysWithinTheBudget() {
    let mac = ScriptedMac()
    let app = mac.app(window: mac.window("Tab", children: [mac.text("page")]))
    app.hangs = ["AXManualAccessibility", "AXEnhancedUserInterface", "AXFocusedWindow"]
    let settings = WindowTextSettings()
    let result = mac.reader([chrome.processIdentifier: app], settings: settings).read(chrome)
    #expect(result.timedOut)
    #expect(result.text.isEmpty)
    #expect(mac.calls == ["app.AXManualAccessibility", "app.AXFocusedWindow"])
    #expect(mac.clock <= settings.windowTimeout + settings.callTimeout)
}

@Test func noFocusedWindowReadsNothing() {
    let mac = ScriptedMac()
    let result = readOnce(mac, nil)
    #expect(result.title == nil)
    #expect(result.text.isEmpty)
    #expect(!result.timedOut)
    #expect(result.fullLength == 0)
}

@Test func readsEachElementOnceWhenTheTreeLoopsBack() {
    let mac = ScriptedMac()
    let inner = mac.node("inner", role: "AXGroup", children: [mac.text("inside")])
    let outer = mac.node("outer", role: "AXGroup", children: [inner])
    let window = mac.window("Loop", children: [outer])
    inner.children.append(outer)
    inner.children.append(window)
    let result = readOnce(mac, window)
    #expect(result.text == "inside")
    #expect(!result.timedOut)
    #expect(mac.reads(of: "outer") == ["outer.AXRole", "outer.AXSubrole", "outer.AXChildren"])
}

@Test func doesNotWalkIntoTheApplicationFromInsideAWindow() {
    let mac = ScriptedMac()
    let otherWindow = mac.window("Other", children: [mac.text("other window")])
    let application = mac.node("application", role: "AXApplication", children: [otherWindow])
    let window = mac.window("Calculator", children: [mac.text("42"), application])
    #expect(readOnce(mac, window).text == "42")
    #expect(mac.reads(of: "application") == ["application.AXRole"])
}

@Test func theFlagOffListMatchesBundleIDsIgnoringCase() {
    #expect(!needsAccessibilityFlag(chrome, offList: ["COM.GOOGLE.chrome"], hasElectronFramework: { _ in false }))
    #expect(needsAccessibilityFlag(chrome, offList: ["com.google.chrome.beta"], hasElectronFramework: { _ in false }))
}

@Test func anAppIsElectronWhenItsBundleShipsTheElectronFramework() throws {
    let bundle = FileManager.default.temporaryDirectory.appendingPathComponent("electron-\(UUID().uuidString).app")
    defer { try? FileManager.default.removeItem(at: bundle) }
    #expect(!bundleHasElectronFramework(bundle))
    try FileManager.default.createDirectory(
        at: bundle.appending(path: "Contents/Frameworks/Electron Framework.framework"), withIntermediateDirectories: true
    )
    #expect(bundleHasElectronFramework(bundle))
}
