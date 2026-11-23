import Foundation

/// The windows of allowed apps the agent still never reads: private browser windows and password-manager pages.
enum WindowExclusion {
    private struct Browser {
        let bundleIDs: [String]
        let privateTitleEndings: [String]
        let passwordPageTitles: [String]
    }

    private static let browsers = [
        Browser(
            bundleIDs: ["com.apple.Safari", "com.apple.SafariTechnologyPreview"],
            privateTitleEndings: ["Private Browsing"],
            passwordPageTitles: []
        ),
        Browser(
            bundleIDs: ["org.mozilla.firefox", "org.mozilla.firefoxdeveloperedition", "org.mozilla.nightly"],
            privateTitleEndings: ["Private Browsing", "(Private Browsing)"],
            passwordPageTitles: ["Passwords"]
        ),
        Browser(
            bundleIDs: ["com.google.Chrome", "org.chromium.Chromium"],
            privateTitleEndings: [" (Incognito)"],
            passwordPageTitles: ["Google Password Manager"]
        ),
        Browser(bundleIDs: ["com.brave.Browser"], privateTitleEndings: [" (Private)"], passwordPageTitles: []),
    ]

    private static let passwordManagerExtensions = [
        "aeblfdkhhhdcdjpifhhbdiojplfjncoa", // 1Password
        "khgocmkkpikpnmmkgmdnfckapcdkgfaf", // 1Password Beta
        "nngceckbapebfimnlniiiahkandclblb", // Bitwarden
        "hdokiejnpimakedhajhdlcegeplioahd", // LastPass
        "fdjamakpfbbddfjaooikfcpapjohcfmg", // Dashlane
        "ghmbeldphafepmbegfdlkpapadhbakde", // Proton Pass
        "kmcfomidfpdkfieipokbalgegidffkal", // Enpass
        "oboonakemofpalcgghocfoadofidjkkk", // KeePassXC-Browser
    ]

    private static let passwordPagePrefixes = [
        "chrome://password-manager",
        "chrome://settings/passwords",
        "brave://password-manager",
        "about:logins",
    ] + passwordManagerExtensions.map { "chrome-extension://\($0)/" }

    /// Whether a focused window is a private browser window or a password-manager page, from its title and the address of the page it shows.
    static func excludesWindow(of application: FocusedApplication, title: String?, document: String?) -> Bool {
        if let document, excludesPage(document) { return true }
        guard let id = application.bundleIdentifier, let title,
              let browser = browsers.first(where: { $0.bundleIDs.contains { bundleID(id, isWithin: $0) } })
        else { return false }
        return browser.privateTitleEndings.contains { title.hasSuffix($0) }
            || browser.passwordPageTitles.contains { title == $0 || title.hasPrefix($0 + " - ") || title.hasPrefix($0 + " — ") }
    }

    /// Whether a window of the app is excluded when neither it nor a page in it gave an address, which holds for the Chromium browsers.
    static func needsAnAddress(_ application: FocusedApplication) -> Bool {
        application.bundleIdentifier.map(chromiumBrowsers.contains) ?? false
    }

    /// Whether a web page's address is a browser's password manager or a password-manager extension.
    static func excludesPage(_ address: String) -> Bool {
        let address = address.lowercased()
        return passwordPagePrefixes.contains { address.hasPrefix($0) }
    }
}
