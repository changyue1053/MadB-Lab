import Foundation

private final class Facts: @unchecked Sendable {
    private let lock = NSLock()
    private var cleaned = false
    private var returned = 0
    func cleanedUp() { lock.withLock { cleaned = true } }
    func waiterReturned() {
        lock.withLock {
            guard cleaned else { fatalError("L04_EARLY_STOP_CONFIRMATION") }
            returned += 1
        }
    }
    func snapshot() -> (Bool, Int) { lock.withLock { (cleaned, returned) } }
}

@main private struct SourceBarrierTests {
    static func main() async throws {
        let entered = DispatchSemaphore(value: 0)
        let resume = DispatchSemaphore(value: 0)
        let facts = Facts()
        let subscription = LocalSubscription {
            entered.signal()
            precondition(resume.wait(timeout: .now() + 10) == .success, "cleanup barrier timed out")
            facts.cleanedUp()
        }
        let collector = Task.detached { try await subscription.collect { _ in } }
        subscription.requestStop()
        let reached = await withCheckedContinuation { result in
            DispatchQueue.global().async {
                result.resume(returning: entered.wait(timeout: .now() + 10) == .success)
            }
        }
        precondition(reached)
        let waiters = (0..<3).map { _ in
            Task.detached { await subscription.awaitStopped(); facts.waiterReturned() }
        }
        let deadline = ContinuousClock.now + .seconds(5)
        while subscription.cleanupSnapshot().waiters != 3 && facts.snapshot().1 == 0 {
            precondition(ContinuousClock.now < deadline, "waiter did not reach the controlled window")
            await Task.yield()
        }
        let held = subscription.cleanupSnapshot()
        precondition(held.finishing && !held.ended && held.waiters == 3)
        precondition(facts.snapshot() == (false, 0), "stop returned before source cleanup")
        do {
            try await subscription.collect { _ in }
            preconditionFailure("a second collector was admitted")
        } catch LocalSourceError.duplicateCollector {}
        resume.signal()
        try await collector.value
        for waiter in waiters { await waiter.value }
        await subscription.awaitStopped()
        let completed = subscription.cleanupSnapshot()
        precondition(completed.ended && completed.waiters == 0 && facts.snapshot() == (true, 3))
        print("L04_SOURCE_BARRIER_OK cleanup-before-confirmation duplicate-collector-rejected")
    }
}
