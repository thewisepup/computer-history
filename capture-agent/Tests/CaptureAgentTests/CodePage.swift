import CoreGraphics
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// A 1440x900 editor window showing 13 px Menlo lines of code, with a sidebar and a toolbar.
struct CodePage {
    static let lineCount = 45
    var lines: [String]
    var caretAfterLine: Int?

    static func lines(from first: Int) -> [String] {
        var state: UInt64 = 1
        let words = ["let", "func", "return", "guard", "self", "value", "record", "window", "image", "spool", "capture", "if", "for", "in", "nil"]
        func next() -> Int {
            state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
            return Int(state >> 33)
        }
        let all = (0..<(first + lineCount)).map { _ in
            String(repeating: " ", count: next() % 4 * 4) + (0..<(next() % 9)).map { _ in words[next() % words.count] }.joined(separator: " ")
        }
        return Array(all[first...])
    }

    init(from first: Int = 0) {
        lines = Self.lines(from: first)
    }

    func image() -> CGImage {
        let context = CGContext(
            data: nil, width: 1440, height: 900, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        )!
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: 1440, height: 900))
        context.setFillColor(CGColor(gray: 0.93, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: 260, height: 900))
        context.setFillColor(CGColor(gray: 0.88, alpha: 1))
        context.fill(CGRect(x: 0, y: 840, width: 1440, height: 60))
        let font = CTFontCreateWithName("Menlo" as CFString, 13, nil)
        let attributes: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0.1, alpha: 1),
        ]
        for (index, text) in lines.enumerated() {
            let y = 810 - CGFloat(index) * 17.68
            let line = CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: attributes))
            context.textPosition = CGPoint(x: 290, y: y)
            CTLineDraw(line, context)
            if caretAfterLine == index {
                let width = CTLineGetTypographicBounds(line, nil, nil, nil)
                context.setFillColor(CGColor(gray: 0, alpha: 1))
                context.fill(CGRect(x: 290 + width + 1, y: y - 4, width: 2, height: 16))
            }
        }
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
