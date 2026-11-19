import Foundation
import Testing
@testable import CaptureAgent

@Test func staysAsleepUntilInputArrivesAfterTheSleepNotification() {
    #expect(isStillAsleep(sleptAt: 100, idleSeconds: 30, uptime: 120))
    #expect(isStillAsleep(sleptAt: 100, idleSeconds: 20, uptime: 120))
    #expect(!isStillAsleep(sleptAt: 100, idleSeconds: 5, uptime: 120))
}
