import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Whether captures take screenshots, and the long edge in pixels and JPEG quality of the images kept.
public struct ScreenshotSettings: Equatable, Sendable {
    public var enabled: Bool
    public var longEdge: Int
    public var quality: Int

    public init(enabled: Bool = true, longEdge: Int = 1440, quality: Int = 60) {
        self.enabled = enabled
        self.longEdge = longEdge
        self.quality = quality
    }
}

struct SavedImage: Equatable {
    let path: String
    let bytes: Int
}

struct ImageStoreError: Error, CustomStringConvertible {
    let description: String
}

/// Saves screenshots as downscaled JPEGs in a folder per local day under the screenshots folder, one file per record id.
struct ImageStore {
    static let folderName = "screenshots"

    let folder: URL
    let settings: ScreenshotSettings
    var timeZone = TimeZone.current

    /// Writes the image and returns its path relative to the folder and its size in bytes.
    func save(_ image: CGImage, id: UUID, at date: Date) throws -> SavedImage {
        let data = try jpeg(try downscaled(image))
        let day = dayStamp(date)
        let path = "\(Self.folderName)/\(day)/\(id.uuidString.lowercased()).jpg"
        try FileManager.default.createDirectory(
            at: folder.appendingPathComponent(Self.folderName).appendingPathComponent(day),
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let file = folder.appendingPathComponent(path)
        guard FileManager.default.createFile(atPath: file.path, contents: data, attributes: [.posixPermissions: 0o600]) else {
            throw ImageStoreError(description: "cannot write \(file.path)")
        }
        return SavedImage(path: path, bytes: data.count)
    }

    private func downscaled(_ image: CGImage) throws -> CGImage {
        let longEdge = max(image.width, image.height)
        guard longEdge > settings.longEdge else { return image }
        let scale = Double(settings.longEdge) / Double(longEdge)
        let width = max(1, Int((Double(image.width) * scale).rounded()))
        let height = max(1, Int((Double(image.height) * scale).rounded()))
        guard let context = CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        ) else { throw ImageStoreError(description: "cannot scale a \(image.width)x\(image.height) image") }
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        guard let scaled = context.makeImage() else { throw ImageStoreError(description: "cannot scale the image") }
        return scaled
    }

    private func jpeg(_ image: CGImage) throws -> Data {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw ImageStoreError(description: "cannot encode JPEG")
        }
        let options = [kCGImageDestinationLossyCompressionQuality: Double(settings.quality) / 100] as CFDictionary
        CGImageDestinationAddImage(destination, image, options)
        guard CGImageDestinationFinalize(destination) else { throw ImageStoreError(description: "cannot encode JPEG") }
        return data as Data
    }

    private func dayStamp(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
}
