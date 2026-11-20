import CoreGraphics

/// A small grey copy of a window's frame, each pixel the average brightness of the same square of points whatever the window's size.
struct FrameThumbnail: Equatable, Sendable {
    static let pointsPerPixel = 9.0
    static let maxLongEdge = 640

    let width: Int
    let height: Int
    let pixels: [UInt8]

    init(width: Int, height: Int, pixels: [UInt8]) {
        self.width = width
        self.height = height
        self.pixels = pixels
    }

    /// The thumbnail of a picture of a window the given size in points: one pixel per square of points, at most the max long edge, never more pixels than the picture.
    init?(_ image: CGImage, points: CGSize) {
        let (sourceWidth, sourceHeight) = (image.width, image.height)
        guard sourceWidth > 0, sourceHeight > 0, points.width > 0, points.height > 0 else { return nil }
        let scale = min(1 / Self.pointsPerPixel, Double(Self.maxLongEdge) / max(points.width, points.height))
        let width = min(sourceWidth, max(1, Int((points.width * scale).rounded())))
        let height = min(sourceHeight, max(1, Int((points.height * scale).rounded())))
        var grey = [UInt8](repeating: 0, count: sourceWidth * sourceHeight)
        let drawn = grey.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(
                data: buffer.baseAddress, width: sourceWidth, height: sourceHeight, bitsPerComponent: 8, bytesPerRow: sourceWidth,
                space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue
            ) else { return false }
            context.draw(image, in: CGRect(x: 0, y: 0, width: sourceWidth, height: sourceHeight))
            return true
        }
        guard drawn else { return nil }
        let columns = (0..<sourceWidth).map { $0 * width / sourceWidth }
        var sums = [Int](repeating: 0, count: width * height)
        var counts = [Int](repeating: 0, count: width * height)
        for row in 0..<sourceHeight {
            let base = row * height / sourceHeight * width
            for column in 0..<sourceWidth {
                sums[base + columns[column]] += Int(grey[row * sourceWidth + column])
                counts[base + columns[column]] += 1
            }
        }
        self.init(width: width, height: height, pixels: zip(sums, counts).map { UInt8(($0 + $1 / 2) / $1) })
    }

    /// How many pixels differ in brightness from the other thumbnail's by more than the tolerance, or nil when the sizes differ.
    func changedPixels(from other: FrameThumbnail, tolerance: Int) -> Int? {
        guard width == other.width, height == other.height else { return nil }
        return zip(pixels, other.pixels).count { abs(Int($0) - Int($1)) > tolerance }
    }
}
