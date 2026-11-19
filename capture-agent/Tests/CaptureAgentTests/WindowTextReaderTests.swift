import Foundation
import Testing
@testable import CaptureAgent

let plainApp = FocusedApplication(
    processIdentifier: 100,
    bundleIdentifier: "com.apple.TextEdit",
    bundleURL: URL(filePath: "/System/Applications/TextEdit.app"),
    name: "TextEdit"
)

let chrome = FocusedApplication(
    processIdentifier: 200,
    bundleIdentifier: "com.google.Chrome",
    bundleURL: URL(filePath: "/Applications/Google Chrome.app"),
    name: "Google Chrome"
)

let cursor = FocusedApplication(
    processIdentifier: 300,
    bundleIdentifier: "com.todesktop.230313mzl4w4u92",
    bundleURL: URL(filePath: "/Applications/Cursor.app"),
    name: "Cursor"
)

func readOnce(_ tree: FakeAccessibilityTree, _ window: FakeElement?, settings: WindowTextSettings = WindowTextSettings()) -> WindowText {
    tree.reader([plainApp.processIdentifier: tree.app(window: window)], settings: settings).read(plainApp)
}

@Test func keepsContentRolesAndDropsControlsAndContainers() {
    let tree = FakeAccessibilityTree()
    let window = tree.window("Notes", children: [
        tree.node("group", role: "AXGroup", ["AXTitle": "group title", "AXDescription": "group description"], children: [
            tree.text("static"),
            tree.node("area", role: "AXTextArea", ["AXValue": "area"]),
            tree.node("field", role: "AXTextField", ["AXValue": "field", "AXDescription": "Search"]),
            tree.node("heading", role: "AXHeading", ["AXTitle": "heading", "AXValue": "2"]),
            tree.node("link", role: "AXLink", ["AXTitle": "link"]),
        ]),
        tree.node("button", role: "AXButton", ["AXTitle": "OK"], children: [tree.text("button label")]),
        tree.node("popup", role: "AXPopUpButton", ["AXValue": "Choice"]),
        tree.node("checkbox", role: "AXCheckBox", ["AXTitle": "Remember"]),
        tree.node("radio", role: "AXRadioButton", ["AXTitle": "Option"]),
        tree.node("row", role: "AXRow", ["AXDescription": "row description"]),
        tree.node("image", role: "AXImage", ["AXDescription": "logo"]),
    ])
    let result = readOnce(tree, window)
    #expect(result.title == "Notes")
    #expect(result.text == "static\narea\nfield\nheading\nlink")
    #expect(!result.cutOff)
    #expect(!result.timedOut)
    #expect(tree.reads(of: "button") == ["button.AXRole", "button.AXSubrole"])
}

@Test func descendsThroughNestedContainers() {
    let tree = FakeAccessibilityTree()
    let window = tree.window("Deep", children: [
        tree.node("outer", role: "AXGroup", children: [
            tree.node("table", role: "AXTable", children: [
                tree.node("row", role: "AXRow", children: [
                    tree.node("cell", role: "AXCell", children: [tree.text("deep text")]),
                ]),
            ]),
            tree.node("unknown", role: "AXUnknown", children: [tree.text("more")]),
        ]),
    ])
    #expect(readOnce(tree, window).text == "deep text\nmore")
}

@Test func neverReadsSecureFieldsOrTheirChildren() {
    let tree = FakeAccessibilityTree()
    let byRole = tree.node("secureRole", role: "AXSecureTextField", ["AXValue": "hunter2"], children: [tree.text("role child")])
    let bySubrole = tree.node(
        "secureSubrole",
        role: "AXTextField",
        ["AXSubrole": "AXSecureTextField", "AXValue": "hunter3"],
        children: [tree.text("subrole child")]
    )
    let window = tree.window("Sign in", children: [tree.text("Password"), byRole, bySubrole])
    let result = readOnce(tree, window)
    #expect(result.text == "Password")
    #expect(tree.reads(of: "secureRole") == ["secureRole.AXRole"])
    #expect(tree.reads(of: "secureSubrole") == ["secureSubrole.AXRole", "secureSubrole.AXSubrole"])
}

@Test func doesNotRepeatTextAParentSharesWithItsChildren() {
    let tree = FakeAccessibilityTree()
    let window = tree.window("Docs", children: [
        tree.node("link", role: "AXLink", ["AXTitle": "Home", "AXDescription": "Home"], children: [tree.text("Home")]),
        tree.node("heading", role: "AXHeading", ["AXTitle": "Intro", "AXValue": "1"], children: [tree.text("Intro")]),
        tree.node("area", role: "AXTextArea", ["AXValue": "draft body"], children: [tree.text("draft body")]),
        tree.node("iconLink", role: "AXLink", ["AXDescription": "Close tab"], children: [
            tree.node("icon", role: "AXImage", ["AXDescription": "x"]),
        ]),
    ])
    #expect(readOnce(tree, window).text == "Home\nIntro\ndraft body\nClose tab")
}

@Test func emptyTextAreaDescendsIntoItsChildren() {
    let tree = FakeAccessibilityTree()
    let window = tree.window("Editor", children: [
        tree.node("area", role: "AXTextArea", ["AXValue": ""], children: [tree.text("line one"), tree.text("line two")]),
    ])
    #expect(readOnce(tree, window).text == "line one\nline two")
}

@Test func capsTextAndKeepsCountingTheFullLength() {
    let tree = FakeAccessibilityTree()
    let window = tree.window("Long", children: [tree.text("abcdef"), tree.text("ghij"), tree.text("klmno")])
    let result = readOnce(tree, window, settings: WindowTextSettings(textCapBytes: 9))
    #expect(result.text == "abcdef\ngh")
    #expect(result.cutOff)
    #expect(result.fullLength == "abcdef\nghij\nklmno".utf8.count)
    #expect(result.sha256 == "b2e67bb70831a96b11c69ab98469b043f19df1b3bed8b014ac461872b0adcf3d")
    #expect(!result.timedOut)
}

@Test func hashesTheKeptText() {
    let tree = FakeAccessibilityTree()
    let result = readOnce(tree, tree.window("Hash", children: [tree.text("abc")]))
    #expect(result.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
}

@Test func perCallTimeoutKeepsTheTextSoFarAndStops() {
    let tree = FakeAccessibilityTree()
    let stuck = tree.text("never read")
    stuck.hangs = ["AXValue"]
    let window = tree.window("Busy", children: [tree.text("before"), stuck, tree.text("after")])
    let result = readOnce(tree, window)
    #expect(result.text == "before")
    #expect(result.timedOut)
    #expect(tree.reads(of: "after").isEmpty)
}

@Test func hungAppCostsOneCallTimeout() {
    let tree = FakeAccessibilityTree()
    let app = tree.app(window: tree.window("Hung", children: [tree.text("unreachable")]))
    app.hangs = ["AXFocusedWindow"]
    let result = tree.reader([plainApp.processIdentifier: app]).read(plainApp)
    #expect(result.timedOut)
    #expect(result.text.isEmpty)
    #expect(result.title == nil)
    #expect(tree.calls == ["app.AXFocusedWindow"])
    #expect(tree.now == tree.callTimeout)
}

@Test func windowTimeoutStopsWithinTheBudgetPlusOneCall() {
    let tree = FakeAccessibilityTree()
    tree.callCost = 0.01
    let window = tree.window("Huge", children: (0..<1_000).map { tree.text("line \($0)") })
    let settings = WindowTextSettings()
    let result = readOnce(tree, window, settings: settings)
    #expect(result.timedOut)
    #expect(!result.text.isEmpty)
    #expect(result.text.hasPrefix("line 0\nline 1\n"))
    #expect(!result.text.contains("line 999"))
    #expect(tree.now <= settings.windowTimeout + tree.callCost + 1e-9)
}

@Test func windowTimeoutAfterTheCapLeavesAPartialFullLength() {
    let tree = FakeAccessibilityTree()
    tree.callCost = 0.01
    let window = tree.window("Huge", children: (0..<1_000).map { _ in tree.text("0123456789") })
    let result = readOnce(tree, window, settings: WindowTextSettings(textCapBytes: 20))
    #expect(result.cutOff)
    #expect(result.timedOut)
    #expect(result.text.utf8.count == 20)
    #expect(result.fullLength > 20)
    #expect(result.fullLength < 1_000 * 11)
}

@Test func setsTheFlagOncePerChromiumProcess() {
    let tree = FakeAccessibilityTree()
    let first = tree.app(window: tree.window("Tab", children: []))
    let relaunched = tree.app(window: tree.window("Tab", children: []))
    let reader = tree.reader([200: first, 201: relaunched])
    _ = reader.read(chrome)
    _ = reader.read(chrome)
    let other = FocusedApplication(processIdentifier: 201, bundleIdentifier: chrome.bundleIdentifier, bundleURL: chrome.bundleURL, name: chrome.name)
    _ = reader.read(other)
    #expect(first.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
    #expect(relaunched.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
}

@Test func setsTheFlagOnElectronApps() {
    let tree = FakeAccessibilityTree()
    let app = tree.app(window: nil)
    let reader = tree.reader([cursor.processIdentifier: app], electronBundles: ["/Applications/Cursor.app/Contents/Frameworks/Electron Framework.framework"])
    _ = reader.read(cursor)
    #expect(app.flagsSet == ["AXManualAccessibility", "AXEnhancedUserInterface"])
}

@Test func skipsTheFlagForOffListAndOtherApps() {
    let tree = FakeAccessibilityTree()
    let chromeApp = tree.app(window: nil)
    let plain = tree.app(window: nil)
    let electron = tree.app(window: nil)
    let reader = tree.reader(
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
    let tree = FakeAccessibilityTree()
    let app = tree.app(window: tree.window("Tab", children: [tree.text("page")]))
    app.hangs = ["AXManualAccessibility"]
    let reader = tree.reader([chrome.processIdentifier: app])
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
    let tree = FakeAccessibilityTree()
    let app = tree.app(window: tree.window("Tab", children: [tree.text("page")]))
    app.hangs = ["AXManualAccessibility", "AXEnhancedUserInterface", "AXFocusedWindow"]
    let settings = WindowTextSettings()
    let result = tree.reader([chrome.processIdentifier: app], settings: settings).read(chrome)
    #expect(result.timedOut)
    #expect(result.text.isEmpty)
    #expect(tree.calls == ["app.AXManualAccessibility", "app.AXFocusedWindow"])
    #expect(tree.now <= settings.windowTimeout + settings.callTimeout)
}

@Test func noFocusedWindowReadsNothing() {
    let tree = FakeAccessibilityTree()
    let result = readOnce(tree, nil)
    #expect(result.title == nil)
    #expect(result.text.isEmpty)
    #expect(!result.timedOut)
    #expect(result.fullLength == 0)
}

@Test func readsEachElementOnceWhenTheTreeLoopsBack() {
    let tree = FakeAccessibilityTree()
    let inner = tree.node("inner", role: "AXGroup", children: [tree.text("inside")])
    let outer = tree.node("outer", role: "AXGroup", children: [inner])
    let window = tree.window("Loop", children: [outer])
    inner.children.append(outer)
    inner.children.append(window)
    let result = readOnce(tree, window)
    #expect(result.text == "inside")
    #expect(!result.timedOut)
    #expect(tree.reads(of: "outer") == ["outer.AXRole", "outer.AXSubrole", "outer.AXChildren"])
}

@Test func doesNotWalkIntoTheApplicationFromInsideAWindow() {
    let tree = FakeAccessibilityTree()
    let otherWindow = tree.window("Other", children: [tree.text("other window")])
    let application = tree.node("application", role: "AXApplication", children: [otherWindow])
    let window = tree.window("Calculator", children: [tree.text("42"), application])
    #expect(readOnce(tree, window).text == "42")
    #expect(tree.reads(of: "application") == ["application.AXRole"])
}

@Test func theFlagOffListMatchesBundleIDsIgnoringCase() {
    #expect(!needsAccessibilityFlag(chrome, offList: ["COM.GOOGLE.chrome"], fileExists: { _ in false }))
    #expect(needsAccessibilityFlag(chrome, offList: ["com.google.chrome.beta"], fileExists: { _ in false }))
}
