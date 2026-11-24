import Foundation
import Testing
@testable import CaptureAgent

@Test func appendWritesOneLinePerRecordToTheOpenFileOnly() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    try writer.append(fixtureRecords[0])
    try writer.append(fixtureRecords[4])
    #expect(try spool.names() == [SpoolWriter.lockFileName, SpoolWriter.openFileName])
    #expect(try spool.lines(SpoolWriter.openFileName) == [line(fixtureRecords[0]), line(fixtureRecords[4]), ""])
}

@Test func finishRenamesTheOpenFileAndTheNextAppendStartsANewOne() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    try writer.append(fixtureRecords[0])
    spool.clock.set("2026-11-18T09:01:00.000Z")
    #expect(try writer.finish()?.lastPathComponent == "20261118T090100.000Z.jsonl")
    try writer.append(fixtureRecords[1])
    spool.clock.set("2026-11-18T09:02:00.000Z")
    try writer.finish()
    #expect(try spool.finishedNames() == ["20261118T090100.000Z.jsonl", "20261118T090200.000Z.jsonl"])
    #expect(try spool.lines("20261118T090100.000Z.jsonl") == [line(fixtureRecords[0]), ""])
    #expect(try spool.lines("20261118T090200.000Z.jsonl") == [line(fixtureRecords[1]), ""])
}

@Test func finishSkipsAnEmptyOrMissingOpenFile() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    #expect(try writer.finish() == nil)
    try spool.writeOpenFile("")
    #expect(try writer.finish() == nil)
    #expect(try spool.finishedNames().isEmpty)
}

@Test func finishesInTheSameMillisecondNeverCollide() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    for record in fixtureRecords.prefix(3) {
        try writer.append(record)
        try writer.finish()
    }
    #expect(try spool.finishedNames() == [
        "20261118T090000.000Z.jsonl", "20261118T090000.001Z.jsonl", "20261118T090000.002Z.jsonl",
    ])
}

@Test func finishedNamesKeepRisingWhenTheClockGoesBack() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    try writer.append(fixtureRecords[0])
    try writer.finish()
    spool.clock.set("2026-11-18T08:00:00.000Z")
    try writer.append(fixtureRecords[1])
    #expect(try writer.finish()?.lastPathComponent == "20261118T090000.001Z.jsonl")
}

@Test func startCreatesTheSpoolFolder() throws {
    let spool = TempSpool()
    #expect(try spool.writer().start() == nil)
    #expect(try spool.names() == [SpoolWriter.lockFileName])
}

@Test func startFinishesALeftoverOpenFileAfterTheFilesAlreadyFinished() throws {
    let spool = TempSpool()
    do {
        let earlier = spool.writer()
        try earlier.start()
        spool.clock.set("2026-11-18T09:05:00.000Z")
        try earlier.append(fixtureRecords[0])
        try earlier.finish()
        try earlier.append(fixtureRecords[1])
    }

    spool.clock.set("2026-11-18T09:04:00.000Z")
    let restarted = spool.writer()
    #expect(try restarted.start()?.lastPathComponent == "20261118T090500.001Z.jsonl")
    #expect(try spool.finishedNames() == ["20261118T090500.000Z.jsonl", "20261118T090500.001Z.jsonl"])
    #expect(try spool.lines("20261118T090500.001Z.jsonl") == [line(fixtureRecords[1]), ""])
}

@Test func startDropsTheTornLastLineOfALeftoverFile() throws {
    let spool = TempSpool()
    let whole = try line(fixtureRecords[0])
    try spool.writeOpenFile(whole + "\n" + String(try line(fixtureRecords[1]).prefix(40)))
    let finished = try #require(try spool.writer().start())
    #expect(try spool.lines(finished.lastPathComponent) == [whole, ""])
}

@Test func startLeavesALeftoverFileWithOnlyATornLineUnfinished() throws {
    let spool = TempSpool()
    try spool.writeOpenFile(String(try line(fixtureRecords[0]).prefix(40)))
    let writer = spool.writer()
    #expect(try writer.start() == nil)
    try writer.append(fixtureRecords[1])
    try writer.finish()
    #expect(try spool.lines("20261118T090000.000Z.jsonl") == [line(fixtureRecords[1]), ""])
}

@Test func aSecondWriterCannotTakeTheSpool() throws {
    let spool = TempSpool()
    let first = spool.writer()
    try first.start()
    let second = spool.writer()
    #expect(throws: SpoolWriter.InUse.self) { try second.append(fixtureRecords[0]) }
    #expect(throws: SpoolWriter.InUse.self) { try second.finish() }
    try first.append(fixtureRecords[1])
    #expect(try spool.lines(SpoolWriter.openFileName) == [line(fixtureRecords[1]), ""])
}

@Test func appendWithoutStartTakesTheSpool() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.append(fixtureRecords[0])
    #expect(throws: SpoolWriter.InUse.self) { try spool.writer().start() }
    #expect(try writer.finish()?.lastPathComponent == "20261118T090000.000Z.jsonl")
}

@Test func theSpoolIsReadableByItsOwnerOnly() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.append(fixtureRecords[0])
    #expect(try spool.mode(nil) == 0o700)
    #expect(try spool.mode(SpoolWriter.lockFileName) == 0o600)
    #expect(try spool.mode(SpoolWriter.openFileName) == 0o600)
    let finished = try #require(try writer.finish())
    #expect(try spool.mode(finished.lastPathComponent) == 0o600)
}

@Test func startTightensAnExistingFolderAndOpenFile() throws {
    let spool = TempSpool()
    try spool.writeOpenFile(try line(fixtureRecords[0]) + "\n")
    let manager = FileManager.default
    try manager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: spool.directory.path)
    try manager.setAttributes([.posixPermissions: 0o644], ofItemAtPath: spool.directory.appendingPathComponent(SpoolWriter.openFileName).path)
    let lock = spool.directory.appendingPathComponent(SpoolWriter.lockFileName).path
    manager.createFile(atPath: lock, contents: nil, attributes: [.posixPermissions: 0o644])
    let leftover = try #require(try spool.writer().start())
    #expect(try spool.mode(nil) == 0o700)
    #expect(try spool.mode(SpoolWriter.lockFileName) == 0o600)
    #expect(try spool.mode(leftover.lastPathComponent) == 0o600)
}

@Test func anAppendThatOpensALeftoverFileDropsItsTornLastLineFirst() throws {
    let spool = TempSpool()
    let whole = try line(fixtureRecords[0])
    try spool.writeOpenFile(whole + "\n" + String(try line(fixtureRecords[1]).prefix(40)))
    try spool.writer().append(fixtureRecords[2])
    #expect(try spool.lines(SpoolWriter.openFileName) == [whole, line(fixtureRecords[2]), ""])
}

@Test func anAppendAfterTheOpenFileWasRemovedWritesToANewOpenFile() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    try writer.append(fixtureRecords[0])
    try FileManager.default.removeItem(at: spool.directory.appendingPathComponent(SpoolWriter.openFileName))
    try writer.append(fixtureRecords[1])
    #expect(try spool.lines(SpoolWriter.openFileName) == [line(fixtureRecords[1]), ""])
    #expect(spool.logs.records.isEmpty)
}

@Test func aFinishAfterTheOpenFileWasRemovedLetsTheNextAppendStartANewOne() throws {
    let spool = TempSpool()
    let writer = spool.writer()
    try writer.start()
    try writer.append(fixtureRecords[0])
    try FileManager.default.removeItem(at: spool.directory.appendingPathComponent(SpoolWriter.openFileName))
    #expect(try writer.finish() == nil)
    try writer.append(fixtureRecords[1])
    #expect(try writer.finish()?.lastPathComponent == "20261118T090000.000Z.jsonl")
    #expect(try spool.lines("20261118T090000.000Z.jsonl") == [line(fixtureRecords[1]), ""])
    #expect(spool.logs.records.isEmpty)
}

@Test func aStartThatFailsAfterTakingTheLockLetsGoOfIt() throws {
    let spool = TempSpool()
    try FileManager.default.createDirectory(at: spool.directory, withIntermediateDirectories: true)
    let denyListing = "user:\(NSUserName()) deny list"
    try changeAccess("+a", denyListing, spool.directory)
    let writer = spool.writer()
    #expect(throws: (any Error).self) { try writer.start() }
    try changeAccess("-a", denyListing, spool.directory)
    #expect(try writer.start() == nil)
}

private func changeAccess(_ operation: String, _ entry: String, _ folder: URL) throws {
    let chmod = Process()
    chmod.executableURL = URL(fileURLWithPath: "/bin/chmod")
    chmod.arguments = [operation, entry, folder.path]
    try chmod.run()
    chmod.waitUntilExit()
    #expect(chmod.terminationStatus == 0)
}
