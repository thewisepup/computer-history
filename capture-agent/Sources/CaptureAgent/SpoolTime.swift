import Foundation

struct SpoolTime: Comparable, Sendable {
    let milliseconds: Int64

    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    init(milliseconds: Int64) {
        self.milliseconds = milliseconds
    }

    init(_ date: Date) {
        milliseconds = Int64((date.timeIntervalSince1970 * 1000).rounded())
    }

    init?(fileStamp: some StringProtocol) {
        let pattern = /(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\.(\d{3})Z/.asciiOnlyDigits()
        guard let match = String(fileStamp).wholeMatch(of: pattern) else { return nil }
        let components = DateComponents(
            year: Int(match.1), month: Int(match.2), day: Int(match.3),
            hour: Int(match.4), minute: Int(match.5), second: Int(match.6)
        )
        guard components.isValidDate(in: Self.utc), let second = Self.utc.date(from: components) else {
            return nil
        }
        milliseconds = Int64(second.timeIntervalSince1970) * 1000 + Int64(match.7)!
    }

    static func < (lhs: SpoolTime, rhs: SpoolTime) -> Bool {
        lhs.milliseconds < rhs.milliseconds
    }

    var iso8601: String {
        format("%04ld-%02ld-%02ldT%02ld:%02ld:%02ld.%03ldZ")
    }

    var fileStamp: String {
        format("%04ld%02ld%02ldT%02ld%02ld%02ld.%03ldZ")
    }

    private func format(_ pattern: String) -> String {
        let (seconds, fraction) = milliseconds.quotientAndRemainder(dividingBy: 1000)
        let date = Date(timeIntervalSince1970: TimeInterval(seconds))
        let parts = Self.utc.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        return String(
            format: pattern,
            parts.year!, parts.month!, parts.day!, parts.hour!, parts.minute!, parts.second!, Int(fraction)
        )
    }
}
