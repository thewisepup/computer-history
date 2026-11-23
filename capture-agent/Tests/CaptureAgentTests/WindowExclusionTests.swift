import Foundation
import Testing
@testable import CaptureAgent

private func app(_ bundleID: String) -> FocusedApplication {
    FocusedApplication(processIdentifier: 1, bundleIdentifier: bundleID, bundleURL: nil, name: bundleID)
}

@Test(arguments: [
    ("com.google.Chrome", "Inbox - Google Chrome (Incognito)"),
    ("com.google.Chrome.canary", "New Tab - Google Chrome Canary (Incognito)"),
    ("org.chromium.Chromium", "New Tab - Chromium (Incognito)"),
    ("com.brave.Browser", "Search - Brave (Private)"),
    ("com.brave.Browser.nightly", "Search - Brave Nightly (Private)"),
    ("org.mozilla.firefox", "Example Domain — Private Browsing"),
    ("org.mozilla.firefox", "Mozilla Firefox — Private Browsing"),
    ("org.mozilla.firefoxdeveloperedition", "Example Domain - (Private Browsing)"),
    ("com.apple.Safari", "Private Browsing"),
    ("com.apple.Safari", "Example Domain, Private Browsing"),
    ("com.apple.SafariTechnologyPreview", "Private Browsing"),
])
func aPrivateWindowIsToldByItsBrowsersTitle(bundleID: String, title: String) {
    #expect(WindowExclusion.excludesWindow(of: app(bundleID), title: title, document: nil))
}

@Test(arguments: [
    ("com.google.Chrome", "Inbox - Google Chrome"),
    ("com.google.Chrome", "Inbox - Google Chrome - Brandon"),
    ("com.google.Chrome", "Inbox - Google Chrome (Guest)"),
    ("com.brave.Browser", "Search - Brave"),
    ("com.brave.Browser", "Search - Brave (Incognito) - Work"),
    ("org.mozilla.firefox", "Example Domain"),
    ("com.apple.Safari", "Example Domain"),
    ("com.apple.TextEdit", "Notes (Incognito)"),
    ("com.apple.TextEdit", "Private Browsing"),
    ("com.microsoft.VSCode", "Passwords"),
])
func anOrdinaryWindowIsNotExcluded(bundleID: String, title: String) {
    #expect(!WindowExclusion.excludesWindow(of: app(bundleID), title: title, document: "https://example.com/"))
}

@Test func aWindowWithNoTitleOrBundleIDIsNotExcluded() {
    #expect(!WindowExclusion.excludesWindow(of: app("com.google.Chrome"), title: nil, document: nil))
    let unnamed = FocusedApplication(processIdentifier: 1, bundleIdentifier: nil, bundleURL: nil, name: "Browser")
    #expect(!WindowExclusion.excludesWindow(of: unnamed, title: "Inbox (Incognito)", document: nil))
}

@Test(arguments: [
    "chrome://password-manager/passwords",
    "CHROME://password-manager",
    "chrome://settings/passwords",
    "brave://password-manager/settings",
    "about:logins",
    "about:logins?filter=github",
    "chrome-extension://aeblfdkhhhdcdjpifhhbdiojplfjncoa/popup/index.html",
    "chrome-extension://khgocmkkpikpnmmkgmdnfckapcdkgfaf/inline/menu",
    "chrome-extension://nngceckbapebfimnlniiiahkandclblb/popup/index.html",
    "chrome-extension://hdokiejnpimakedhajhdlcegeplioahd/vault.html",
    "chrome-extension://fdjamakpfbbddfjaooikfcpapjohcfmg/popup.html",
    "chrome-extension://ghmbeldphafepmbegfdlkpapadhbakde/popup.html",
    "chrome-extension://kmcfomidfpdkfieipokbalgegidffkal/popup.html",
    "chrome-extension://oboonakemofpalcgghocfoadofidjkkk/popup.html",
])
func aPasswordManagerPageIsExcludedByItsAddress(address: String) {
    #expect(WindowExclusion.excludesPage(address))
    #expect(WindowExclusion.excludesWindow(of: app("com.google.Chrome"), title: "Untitled", document: address))
}

@Test(arguments: [
    "chrome://settings/",
    "chrome://newtab/",
    "https://example.com/password-manager",
    "https://example.com/?u=chrome://password-manager",
    "chrome-extension://abcdefghijklmnopabcdefghijklmnop/popup.html",
    "about:blank",
    "",
])
func anOrdinaryPageIsNotExcluded(address: String) {
    #expect(!WindowExclusion.excludesPage(address))
}

@Test func aPasswordManagerPageIsExcludedByItsTitleWhereTheAddressIsUnknown() {
    #expect(WindowExclusion.excludesWindow(of: app("com.google.Chrome"), title: "Google Password Manager - Google Chrome", document: nil))
    #expect(WindowExclusion.excludesWindow(of: app("org.mozilla.firefox"), title: "Passwords", document: nil))
    #expect(WindowExclusion.excludesWindow(of: app("org.mozilla.firefox"), title: "Passwords — Private Browsing", document: nil))
    #expect(!WindowExclusion.excludesWindow(of: app("org.mozilla.firefox"), title: "Passwords for beginners", document: nil))
    #expect(!WindowExclusion.excludesWindow(of: app("com.apple.Safari"), title: "Google Password Manager", document: nil))
}
