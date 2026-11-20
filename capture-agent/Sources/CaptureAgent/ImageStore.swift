import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

public struct SavedImage: Equatable, Sendable {
    let path: String
    let bytes: Int
}

struct ImageStoreError: Error, CustomStringConvertible {
    let description: String
}

/// Where kept screenshots are saved.
public protocol ImageStore {
    func save(_ image: CGImage, id: UUID, at date: Date) throws -> SavedImage
    func remove(_ path: String)
}

/// Saves screenshots as downscaled JPEGs in a folder per local day under the screenshots folder, one file per record id.
public struct JPEGImageStore: ImageStore, Sendable {
    public static let folderName = "screenshots"

    let folder: URL
    let longEdge: Int
    let quality: Int
    var timeZone = TimeZone.autoupdatingCurrent

    public init(folder: URL, longEdge: Int, quality: Int) {
        self.folder = folder
        self.longEdge = longEdge
        self.quality = quality
    }

    init(folder: URL, longEdge: Int, quality: Int, timeZone: TimeZone) {
        self.init(folder: folder, longEdge: longEdge, quality: quality)
        self.timeZone = timeZone
    }

    /// Writes the image and returns its path relative to the folder and its size in bytes.
    public func save(_ image: CGImage, id: UUID, at date: Date) throws -> SavedImage {
        let data = try jpeg(try downscaled(image))
        let day = dayStamp(date)
        let path = "\(Self.folderName)/\(day)/\(id.uuidString.lowercased()).jpg"
        let root = folder.appendingPathComponent(Self.folderName)
        for directory in [root, root.appendingPathComponent(day)] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            chmod(directory.path, 0o700)
        }
        let file = folder.appendingPathComponent(path)
        guard FileManager.default.createFile(atPath: file.path, contents: data, attributes: [.posixPermissions: 0o600]) else {
            throw ImageStoreError(description: "cannot write \(file.path)")
        }
        return SavedImage(path: path, bytes: data.count)
    }

    /// Deletes a saved image by its path relative to the folder.
    public func remove(_ path: String) {
        try? FileManager.default.removeItem(at: folder.appendingPathComponent(path))
    }

    private func downscaled(_ image: CGImage) throws -> CGImage {
        let longEdge = max(image.width, image.height)
        guard longEdge > self.longEdge else { return image }
        let scale = Double(self.longEdge) / Double(longEdge)
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
        let options = [kCGImageDestinationLossyCompressionQuality: Double(quality) / 100] as CFDictionary
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
