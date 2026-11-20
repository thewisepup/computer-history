import CoreGraphics

/// A 64-bit perceptual hash of a frame, written as 16 lowercase hex digits.
struct FrameHash: Equatable, Sendable {
    let bits: UInt64

    init(bits: UInt64) {
        self.bits = bits
    }

    var hex: String { String(format: "%016llx", bits) }

    /// How many of the 64 bits differ between the two hashes.
    func distance(to other: FrameHash) -> Int { (bits ^ other.bits).nonzeroBitCount }
}

/// The difference hash of the image: each bit says whether a pixel of a 9x8 grey thumbnail is brighter than its right neighbour.
func differenceHash(_ image: CGImage) -> FrameHash? {
    let width = 9, height = 8
    var pixels = [UInt8](repeating: 0, count: width * height)
    let drawn = pixels.withUnsafeMutableBytes { buffer -> Bool in
        guard let context = CGContext(
            data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width,
            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue
        ) else { return false }
        context.interpolationQuality = .medium
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        return true
    }
    guard drawn else { return nil }
    var hash: UInt64 = 0
    for row in 0..<height {
        for column in 0..<(width - 1) {
            hash = hash << 1 | (pixels[row * width + column] > pixels[row * width + column + 1] ? 1 : 0)
        }
    }
    return FrameHash(bits: hash)
}
