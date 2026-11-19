import Foundation

/// Why a scripted session may not use these folders, or nil when neither is inside the agent's default folder and the folder holds no database.
func scriptedSessionRefusal(_ settings: AgentSettings, homes: [URL]) -> String? {
    for home in homes {
        let real = AgentSettings.defaultFolder(home: home)
        for (what, folder) in [("folder", settings.folder), ("spool", settings.spoolDirectory)]
        where resolved(folder).pathComponents.starts(with: resolved(real).pathComponents) {
            return "refusing a scripted session: the \(what) \(folder.path) is inside the agent's real folder \(real.path); "
                + "set \(AgentSettings.databaseEnvironmentVariable) to a database path in an empty scratch folder"
        }
    }
    let names = (try? FileManager.default.contentsOfDirectory(atPath: settings.folder.path)) ?? []
    if let database = names.sorted().first(where: { $0.hasSuffix(".db") }) {
        return "refusing a scripted session: \(settings.folder.path) already holds a database (\(database)); use an empty scratch folder"
    }
    return nil
}

/// The current user's home folders as HOME, Foundation and the user database each report them.
public func userHomes() -> [URL] {
    var homes = [FileManager.default.homeDirectoryForCurrentUser]
    if let home = ProcessInfo.processInfo.environment["HOME"], !home.isEmpty { homes.append(URL(fileURLWithPath: home)) }
    if let entry = getpwuid(getuid()), let directory = entry.pointee.pw_dir { homes.append(URL(fileURLWithPath: String(cString: directory))) }
    return homes
}

private func resolved(_ url: URL) -> URL {
    var existing = url.standardizedFileURL
    var rest: [String] = []
    while !FileManager.default.fileExists(atPath: existing.path), existing.pathComponents.count > 1 {
        rest.insert(existing.lastPathComponent, at: 0)
        existing.deleteLastPathComponent()
    }
    return rest.reduce(existing.resolvingSymlinksInPath()) { $0.appendingPathComponent($1) }
}
