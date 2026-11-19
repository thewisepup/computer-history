import Foundation

/// The apps whose windows the agent never reads, matched by bundle id ignoring case.
public struct Denylist: Equatable, Sendable {
    public static let builtIn: Set<String> = [
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.apple.keychainaccess",
        "com.apple.Passwords",
    ]

    public let bundleIDs: Set<String>

    /// The built-in apps plus the given bundle ids.
    public init(adding bundleIDs: some Sequence<String> = []) {
        self.bundleIDs = Set(Self.builtIn.union(bundleIDs).map { $0.lowercased() })
    }

    public func contains(_ application: FocusedApplication) -> Bool {
        application.bundleIdentifier.map { bundleIDs.contains($0.lowercased()) } ?? false
    }
}
