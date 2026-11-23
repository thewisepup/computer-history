import Foundation

/// The apps whose windows the agent never reads, matched by bundle id or a prefix of it, ignoring case.
public struct Denylist: Equatable, Sendable {
    public static let builtIn: Set<String> = [
        "com.1password",
        "com.agilebits",
        "com.apple.keychainaccess",
        "com.apple.Passwords",
        "com.bitwarden.desktop",
        "com.dashlane",
        "com.lastpass",
        "in.sinew.Enpass-Desktop",
        "me.proton.pass",
        "org.keepassxc.keepassxc",
    ]

    public let bundleIDs: Set<String>

    /// The built-in apps plus the given bundle ids.
    public init(adding bundleIDs: some Sequence<String> = []) {
        self.bundleIDs = Set(Self.builtIn.union(bundleIDs).map { $0.lowercased() })
    }

    public func contains(_ application: FocusedApplication) -> Bool {
        guard let id = application.bundleIdentifier else { return false }
        return bundleIDs.contains { bundleID(id, isWithin: $0) }
    }
}

/// Whether a bundle id is the given one or sits under it, ignoring case.
func bundleID(_ id: String, isWithin prefix: String) -> Bool {
    let id = id.lowercased()
    let prefix = prefix.lowercased()
    return id == prefix || id.hasPrefix(prefix + ".")
}
