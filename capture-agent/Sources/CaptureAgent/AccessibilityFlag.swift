import Foundation

let accessibilityFlags = ["AXManualAccessibility", "AXEnhancedUserInterface"]

let chromiumBrowsers: Set<String> = [
    "com.google.Chrome",
    "com.google.Chrome.beta",
    "com.google.Chrome.dev",
    "com.google.Chrome.canary",
    "org.chromium.Chromium",
    "com.brave.Browser",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "com.vivaldi.Vivaldi",
    "com.operasoftware.Opera",
]

/// Whether the app bundle ships the Electron framework.
func bundleHasElectronFramework(_ bundle: URL) -> Bool {
    FileManager.default.fileExists(atPath: bundle.appending(path: "Contents/Frameworks/Electron Framework.framework").path)
}

/// Whether an app should get the accessibility flags: Chromium browsers and Electron apps, unless off-listed by bundle id ignoring case.
func needsAccessibilityFlag(_ application: FocusedApplication, offList: Set<String>, hasElectronFramework: (URL) -> Bool) -> Bool {
    if let id = application.bundleIdentifier {
        if offList.contains(where: { $0.caseInsensitiveCompare(id) == .orderedSame }) { return false }
        if chromiumBrowsers.contains(id) { return true }
    }
    guard let bundle = application.bundleURL else { return false }
    return hasElectronFramework(bundle)
}
