import Foundation
import ImageIO
import Testing
@testable import CaptureAgent

final class TempImageFolder {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("image-tests-\(UUID().uuidString)", isDirectory: true)

    deinit { try? FileManager.default.removeItem(at: url) }

    func store(longEdge: Int = 1440, quality: Int = 60, timeZone: String = "America/Los_Angeles") -> JPEGImageStore {
        JPEGImageStore(folder: url, longEdge: longEdge, quality: quality, timeZone: TimeZone(identifier: timeZone)!)
    }
}

func pixelSize(ofJPEG file: URL) -> (width: Int, height: Int, type: String)? {
    guard let source = CGImageSourceCreateWithURL(file as CFURL, nil),
          let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
          let width = properties[kCGImagePropertyPixelWidth] as? Int,
          let height = properties[kCGImagePropertyPixelHeight] as? Int,
          let type = CGImageSourceGetType(source) as String?
    else { return nil }
    return (width, height, type)
}

@Test func savesAJPEGInTheDayFolderNamedByRecordIDAndReportsItsPathAndSize() throws {
    let folder = TempImageFolder()
    let id = fixtureID(11)
    let saved = try folder.store().save(fixtureImage(width: 3000, height: 2000), id: id, at: utc("2026-11-18T09:00:00.000Z"))
    #expect(saved.path == "screenshots/2026-11-18/6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e11.jpg")
    let file = folder.url.appendingPathComponent(saved.path)
    let size = try #require(pixelSize(ofJPEG: file))
    #expect((size.width, size.height) == (1440, 960))
    #expect(size.type == "public.jpeg")
    #expect(saved.bytes == (try FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int))
}

@Test(arguments: [
    (1000, 3000, 480, 1440),
    (800, 600, 800, 600),
    (1440, 900, 1440, 900),
])
func scalesTheLongEdgeDownAndNeverEnlarges(width: Int, height: Int, storedWidth: Int, storedHeight: Int) throws {
    let folder = TempImageFolder()
    let saved = try folder.store().save(fixtureImage(width: width, height: height), id: UUID(), at: Date())
    let size = try #require(pixelSize(ofJPEG: folder.url.appendingPathComponent(saved.path)))
    #expect((size.width, size.height) == (storedWidth, storedHeight))
}

@Test func theDayFolderFollowsTheLocalDate() throws {
    let folder = TempImageFolder()
    let late = utc("2026-11-18T23:30:00.000Z")
    #expect(try folder.store(timeZone: "America/Los_Angeles").save(fixtureImage(width: 10, height: 10), id: fixtureID(1), at: late)
        .path.hasPrefix("screenshots/2026-11-18/"))
    #expect(try folder.store(timeZone: "Asia/Tokyo").save(fixtureImage(width: 10, height: 10), id: fixtureID(2), at: late)
        .path.hasPrefix("screenshots/2026-11-19/"))
}

@Test func aLowerQualityMakesASmallerFile() throws {
    let folder = TempImageFolder()
    let image = fixtureImage(width: 1200, height: 800)
    let low = try folder.store(quality: 20).save(image, id: UUID(), at: Date())
    let high = try folder.store(quality: 95).save(image, id: UUID(), at: Date())
    #expect(low.bytes < high.bytes)
}

@Test func onlyTheOwnerCanReadTheImages() throws {
    let folder = TempImageFolder()
    let saved = try folder.store().save(fixtureImage(width: 10, height: 10), id: UUID(), at: Date())
    let mode = { (path: String) in
        (try FileManager.default.attributesOfItem(atPath: path)[.posixPermissions] as? Int) ?? -1
    }
    #expect(try mode(folder.url.appendingPathComponent(JPEGImageStore.folderName).path) == 0o700)
    #expect(try mode(folder.url.appendingPathComponent(saved.path).deletingLastPathComponent().path) == 0o700)
    #expect(try mode(folder.url.appendingPathComponent(saved.path).path) == 0o600)
}

@Test func aFolderThatCannotBeWrittenThrows() throws {
    let folder = TempImageFolder()
    try FileManager.default.createDirectory(at: folder.url, withIntermediateDirectories: true)
    try Data().write(to: folder.url.appendingPathComponent(JPEGImageStore.folderName))
    #expect(throws: (any Error).self) {
        try folder.store().save(fixtureImage(width: 10, height: 10), id: UUID(), at: Date())
    }
}
