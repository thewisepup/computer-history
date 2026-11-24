/// The states of one machine: each gives the state an event moves it to, or nil when that event is not allowed from it.
protocol StateMachine: Equatable {
    associatedtype Event
    static var name: String { get }
    func after(_ event: Event) -> Self?
}

extension StateMachine {
    /// Moves to the state the event leads to and returns true, or logs the event as not allowed, keeps the state and returns false.
    @discardableResult
    mutating func handle(_ event: Event, log: AgentLog, _ category: AgentLog.Category) -> Bool {
        guard let next = after(event) else {
            log.error(category, "\(Self.name) refused \(caseName(event)) in state \(caseName(self)), state kept")
            return false
        }
        self = next
        return true
    }
}

/// The name of an enum value's case without its associated values.
func caseName(_ value: Any) -> String {
    Mirror(reflecting: value).children.first?.label ?? String(describing: value)
}
