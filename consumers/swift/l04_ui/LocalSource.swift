import Foundation
import MadBObservation

// An independent, pure Swift consumer source; this is not a native SDK emulator.
final class LocalStateHub: @unchecked Sendable {
    private let lock = NSLock()
    private var subscriptions: [UUID: LocalSubscription] = [:]
    private var created = 0
    private var drained = 0
    private var closed = false

    func subscribe() -> MadBStateSource<Int> {
        let id = UUID()
        let subscription = LocalSubscription { [weak self] in self?.finished(id) }
        lock.withLock {
            precondition(!closed && subscriptions.count < 8)
            subscriptions[id] = subscription
            created += 1
        }
        return subscription.source()
    }

    func publish(_ value: Int) {
        let selected = lock.withLock { Array(subscriptions.values) }
        for subscription in selected { subscription.publish(value) }
    }

    func counts() -> [String: Int] {
        lock.withLock { ["created": created, "active": subscriptions.count,
                         "drained": drained, "sourceClosed": closed ? 1 : 0] }
    }

    func close() {
        lock.withLock { precondition(subscriptions.isEmpty && !closed); closed = true }
    }

    private func finished(_ id: UUID) {
        lock.withLock {
            precondition(subscriptions.removeValue(forKey: id) != nil)
            drained += 1
        }
    }
}

enum LocalSourceError: Error { case duplicateCollector }

final class LocalSubscription: @unchecked Sendable {
    private let stream: AsyncStream<Int>
    private let continuation: AsyncStream<Int>.Continuation
    private let lock = NSLock()
    private var collecting = false
    private var finishing = false
    private var ended = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private let didEnd: @Sendable () -> Void

    init(didEnd: @escaping @Sendable () -> Void) {
        (stream, continuation) = AsyncStream.makeStream(bufferingPolicy: .bufferingNewest(1))
        self.didEnd = didEnd
    }

    func publish(_ value: Int) { continuation.yield(value) }
    func requestStop() { continuation.finish() }

    func collect(_ receive: MadBStateSource<Int>.Receiver) async throws {
        let admitted = lock.withLock {
            if collecting { return false }
            collecting = true
            return true
        }
        guard admitted else { throw LocalSourceError.duplicateCollector }
        for await value in stream { await receive(value) }
        finish()
    }

    func awaitStopped() async {
        await withCheckedContinuation { waiter in
            let ready = lock.withLock {
                if ended { return true }
                precondition(waiters.count < 4)
                waiters.append(waiter)
                return false
            }
            if ready { waiter.resume() }
        }
    }

    // Lab-source observation only, for the independent cleanup barrier test.
    func cleanupSnapshot() -> (finishing: Bool, ended: Bool, waiters: Int) {
        lock.withLock { (finishing, ended, waiters.count) }
    }

    func source() -> MadBStateSource<Int> {
        MadBStateSource(
            collect: { [self] receive in
                try await collect(receive)
            },
            requestStop: { [self] in requestStop() },
            awaitStopped: { [self] in await awaitStopped() }
        )
    }

    private func finish() {
        lock.withLock {
            precondition(collecting && !finishing && !ended)
            finishing = true
        }
        // Complete shared-owner cleanup without holding the subscription lock.
        // No waiter may observe ended until this responsibility has returned.
        didEnd()
        let pending = lock.withLock {
            precondition(finishing && !ended)
            ended = true
            let pending = waiters
            waiters.removeAll()
            return pending
        }
        for waiter in pending { waiter.resume() }
    }
}
