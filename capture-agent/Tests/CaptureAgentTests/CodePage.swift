import CoreGraphics
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// An editor window of the given size in points showing Menlo lines of code beside a sidebar, drawn at the pixels the agent asks for: two per point, at most 1440 on the long edge.
struct CodePage {
    var size = CGSize(width: 1440, height: 900)
    var fontSize: CGFloat = 13
    var first = 0
    var typed = false
    var caret = false

    var lineHeight: CGFloat { fontSize * 1.36 }
    var toolbar: CGFloat { size.height >= 300 ? 60 : 0 }
    var sidebar: CGFloat { min(260, size.width / 5) }
    var visibleLines: Int { Int((size.height - toolbar - 30) / lineHeight) + 1 }
    var editedLine: Int { min(10, visibleLines - 1) }
    var pixelScale: CGFloat { min(2, 1440 / max(size.width, size.height)) }
    var bounds: CGRect { CGRect(origin: CGPoint(x: 0, y: 25), size: size) }

    static func lines(from first: Int, count: Int) -> [String] {
        var state: UInt64 = 1
        let words = ["let", "func", "return", "guard", "self", "value", "record", "window", "image", "spool", "capture", "if", "for", "in", "nil"]
        func next() -> Int {
            state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
            return Int(state >> 33)
        }
        let all = (0..<(first + count)).map { _ in
            String(repeating: " ", count: next() % 4 * 4) + (0..<(1 + next() % 8)).map { _ in words[next() % words.count] }.joined(separator: " ")
        }
        return Array(all[first...])
    }

    func image(scale: CGFloat? = nil) -> CGImage {
        let scale = scale ?? pixelScale
        let context = CGContext(
            data: nil, width: Int((size.width * scale).rounded()), height: Int((size.height * scale).rounded()), bitsPerComponent: 8,
            bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        )!
        context.scaleBy(x: scale, y: scale)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(origin: .zero, size: size))
        context.setFillColor(CGColor(gray: 0.93, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: sidebar, height: size.height))
        context.setFillColor(CGColor(gray: 0.88, alpha: 1))
        context.fill(CGRect(x: 0, y: size.height - toolbar, width: size.width, height: toolbar))
        let font = CTFontCreateWithName("Menlo" as CFString, fontSize, nil)
        let attributes: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0.1, alpha: 1),
        ]
        var lines = Self.lines(from: first, count: visibleLines).map { size.width < 600 ? $0.trimmingCharacters(in: .whitespaces) : $0 }
        lines[editedLine] = typed ? "capture window" : ""
        let left = sidebar + min(30, size.width / 20)
        for (index, text) in lines.enumerated() {
            let y = size.height - toolbar - 30 - CGFloat(index) * lineHeight
            context.textPosition = CGPoint(x: left, y: y)
            CTLineDraw(CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: attributes)), context)
            if caret, index == editedLine {
                context.setFillColor(CGColor(gray: 0, alpha: 1))
                context.fill(CGRect(x: left + 1, y: y - fontSize * 0.3, width: 2, height: fontSize * 1.2))
            }
        }
        return context.makeImage()!
    }

    /// The page drawn at twice the pixels and scaled down to the agent's, as a different rasterization of the same window.
    func imageScaledFromTwiceTheSize() -> CGImage {
        let large = image(scale: pixelScale * 2)
        let small = image()
        let context = CGContext(
            data: nil, width: small.width, height: small.height, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        )!
        context.interpolationQuality = .high
        context.draw(large, in: CGRect(x: 0, y: 0, width: small.width, height: small.height))
        return context.makeImage()!
    }
}

/// The image after a JPEG encode and decode at the given quality.
func reencoded(_ image: CGImage, quality: Double) -> CGImage {
    let data = NSMutableData()
    let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
    CGImageDestinationFinalize(destination)
    return CGImageSourceCreateImageAtIndex(CGImageSourceCreateWithData(data, nil)!, 0, nil)!
}

/// A grey image with the given pixels, row by row.
func greyImage(_ pixels: [UInt8], width: Int) -> CGImage {
    CGImage(
        width: width, height: pixels.count / width, bitsPerComponent: 8, bitsPerPixel: 8, bytesPerRow: width,
        space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
        provider: CGDataProvider(data: Data(pixels) as CFData)!, decode: nil, shouldInterpolate: false, intent: .defaultIntent
    )!
}
