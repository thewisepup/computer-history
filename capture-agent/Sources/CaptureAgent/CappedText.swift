import Foundation

struct CappedText {
    let capBytes: Int
    private(set) var text = ""
    private(set) var keptBytes = 0
    private(set) var fullLength = 0
    private(set) var cutOff = false
    private(set) var pieces = 0

    init(capBytes: Int) {
        self.capBytes = capBytes
    }

    mutating func append(_ piece: String) {
        let separator = pieces == 0 ? "" : "\n"
        let pieceBytes = separator.utf8.count + piece.utf8.count
        pieces += 1
        fullLength += pieceBytes
        guard !cutOff else { return }
        if keptBytes + pieceBytes <= capBytes {
            text += separator + piece
            keptBytes += pieceBytes
            return
        }
        cutOff = true
        var room = capBytes - keptBytes - separator.utf8.count
        var prefix = ""
        for character in piece {
            let size = character.utf8.count
            if size > room { break }
            prefix.append(character)
            room -= size
        }
        guard !prefix.isEmpty else { return }
        text += separator + prefix
        keptBytes += separator.utf8.count + prefix.utf8.count
    }
}
