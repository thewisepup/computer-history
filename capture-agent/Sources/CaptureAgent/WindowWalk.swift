import Foundation

private let valueRoles: Set<String> = ["AXStaticText", "AXTextArea", "AXTextField"]
private let nameRoles: Set<String> = ["AXHeading", "AXLink"]
private let controlRoles: Set<String> = ["AXButton", "AXPopUpButton", "AXCheckBox", "AXRadioButton"]
private let secureRole = "AXSecureTextField"

struct WindowWalk<Element: AccessibilityElement> {
    private(set) var text: CappedText
    private(set) var timedOut = false
    let deadline: TimeInterval
    let now: () -> TimeInterval

    init(capBytes: Int, deadline: TimeInterval, now: @escaping () -> TimeInterval) {
        self.text = CappedText(capBytes: capBytes)
        self.deadline = deadline
        self.now = now
    }

    mutating func call<Value>(_ body: () -> AccessibilityResult<Value>) -> Value? {
        guard !timedOut else { return nil }
        guard now() < deadline else {
            timedOut = true
            return nil
        }
        switch body() {
        case .value(let value): return value
        case .missing: return nil
        case .timedOut:
            timedOut = true
            return nil
        }
    }

    mutating func visit(_ element: Element) {
        let role = call { element.string("AXRole") }
        guard !timedOut, role != secureRole else { return }
        let subrole = call { element.string("AXSubrole") }
        guard !timedOut, subrole != secureRole, !controlRoles.contains(role ?? "") else { return }
        if valueRoles.contains(role ?? "") {
            if let value = call({ element.string("AXValue") }), !value.isEmpty {
                text.append(value)
                return
            }
            visitChildren(of: element)
        } else if nameRoles.contains(role ?? "") {
            let piecesBefore = text.pieces
            visitChildren(of: element)
            guard !timedOut, text.pieces == piecesBefore else { return }
            if let name = nonEmpty(call { element.string("AXTitle") }) ?? nonEmpty(call { element.string("AXDescription") }) {
                text.append(name)
            }
        } else {
            visitChildren(of: element)
        }
    }

    private mutating func visitChildren(of element: Element) {
        for child in call({ element.elements("AXChildren") }) ?? [] {
            guard !timedOut else { return }
            visit(child)
        }
    }
}

private func nonEmpty(_ string: String?) -> String? {
    string?.isEmpty == false ? string : nil
}
