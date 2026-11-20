import Foundation
import Vision

/// Reads the English text in the picture at the file with Vision's accurate recognizer and language correction. Returns one line per recognized line, in the order Vision reads them.
public func recognizeText(inImageAt file: URL) throws -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = true
    return try autoreleasepool {
        try VNImageRequestHandler(url: file).perform([request])
        return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
    }
}
