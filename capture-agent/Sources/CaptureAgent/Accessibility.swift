import ApplicationServices

/// Reports whether this process may use the Accessibility API, showing the system prompt if asked and access is missing.
public func isAccessibilityTrusted(prompt: Bool) -> Bool {
    let options = ["AXTrustedCheckOptionPrompt": prompt] as CFDictionary
    return AXIsProcessTrustedWithOptions(options)
}
