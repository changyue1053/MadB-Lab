import Foundation
import MadBObservation
import MadBSkie
import Observation

private struct PublishedValue {
    let id: String
    let text: String
    let bytes: [UInt8]

    @MainActor func native() -> MadBSkie.Value {
        let buffer = KotlinByteArray(size: Int32(bytes.count))
        for (index, value) in bytes.enumerated() {
            buffer.set(index: Int32(index), value: Int8(bitPattern: value))
        }
        return MadBSkie.Value(id: id, sequence: nil, text: text, bytes: buffer, phase: .open)
    }

    func matches(_ snapshot: MadBValueSnapshot?) -> Bool {
        guard let snapshot else { return false }
        return snapshot.id == id && snapshot.text == text && snapshot.bytes == bytes
            && snapshot.sequence == nil && snapshot.phase == .open
    }
}

@MainActor final class NativePageSession {
    let id = UUID()
    let model = MadBStateModel<MadBValueSnapshot>()
    var started = false
    var stopping = false
}

@MainActor private final class WeakNativeModel {
    weak var value: MadBStateModel<MadBValueSnapshot>?
    init(_ value: MadBStateModel<MadBValueSnapshot>) { self.value = value }
}

func displayedSnapshot(_ snapshot: MadBValueSnapshot?) -> String {
    guard let snapshot else { return "nil" }
    let text = snapshot.text.utf8.map { String(format: "%02x", $0) }.joined()
    let bytes = snapshot.bytes.map { String(format: "%02x", $0) }.joined()
    return snapshot.id + "|" + text + "|" + bytes
}

@MainActor @Observable final class NativeApplicationOwner {
    var displayedPage: NativePageSession?
    private(set) var summary = "starting"
    private(set) var ordinaryDisplay = "nil"
    private(set) var finished = false
    private(set) var busy = false

    // This is the only engine owner. The ordinary collector and each page borrow it.
    @ObservationIgnored private let engineOwner: MadBEngineHandle
    @ObservationIgnored private var ordinarySubscription: MadBSubscriptionHandle?
    @ObservationIgnored private var ordinaryTask: Task<Void, any Error>?
    @ObservationIgnored private var ordinarySnapshot: MadBValueSnapshot?
    @ObservationIgnored private var pages: [UUID: NativePageSession] = [:]
    @ObservationIgnored private var weakModels: [UUID: WeakNativeModel] = [:]
    @ObservationIgnored private var cleanupTasks: [UUID: Task<Void, Never>] = [:]
    @ObservationIgnored private var releaseTasks: [UUID: Task<Void, Never>] = [:]
    @ObservationIgnored private var publicationTask: Task<Void, Never>?
    @ObservationIgnored private var closeTask: Task<Void, Never>?
    @ObservationIgnored private var nativeCleanupConfirmed = false
    @ObservationIgnored private var publishedIndex = 0
    @ObservationIgnored private var createdPages = 0
    @ObservationIgnored private var drainedPages = 0
    @ObservationIgnored private var releasedPages = 0
    @ObservationIgnored private var pageFactories = 0
    @ObservationIgnored private var ordinaryDeliveries = 0
    @ObservationIgnored private let nonce: String
    @ObservationIgnored private let profile: String
    @ObservationIgnored private let interface: String
    @ObservationIgnored private let logURL: URL

    private static let values = [
        PublishedValue(id: "ascii", text: "native page one", bytes: [0, 127, 128, 255]),
        PublishedValue(id: "after-1", text: "after one", bytes: [255, 0]),
        PublishedValue(id: "unicode", text: "你好é🙂", bytes: [0, 195, 169, 255]),
        PublishedValue(id: "after-2", text: "页面退出后", bytes: [128, 1]),
        PublishedValue(id: "nul", text: "left\0right", bytes: []),
        PublishedValue(id: "after-3", text: "", bytes: [0]),
    ]

    init() {
        let environment = ProcessInfo.processInfo.environment
        guard let nonce = environment["MADB_L04_NONCE"], !nonce.isEmpty,
              let profile = environment["MADB_L04_PROFILE"],
              let interface = environment["MADB_L04_INTERFACE"],
              let path = environment["MADB_L04_LOG_PATH"], path.hasPrefix("/") else {
            preconditionFailure("runner must supply frozen identities and a new absolute log path")
        }
        self.nonce = nonce; self.profile = profile; self.interface = interface
        logURL = URL(fileURLWithPath: path)
        precondition(profileIdentity() == profile && interfaceIdentity() == interface,
                     "loaded native identity differs")
        precondition(bootstrapVersion() == 1 && nativeAbiVersion() == 1, "native ABI differs")
        let zero = "sha256:" + String(repeating: "0", count: 64)
        let wrong = profile == zero ? "sha256:" + String(repeating: "1", count: 64) : zero
        do {
            _ = try MadBEngineHandle(expectedProfile: wrong)
            preconditionFailure("wrong profile acquired an engine")
        } catch {
            let failure = (error as NSError).kotlinException as? BoundaryFailure
            precondition(failure?.code == "ProfileMismatch", "wrong profile failed for another reason")
        }
        engineOwner = try! MadBEngineHandle(expectedProfile: profile)
        precondition(!FileManager.default.fileExists(atPath: path), "evidence already exists")
        precondition(FileManager.default.createFile(atPath: path, contents: Data()), "cannot create evidence")
        record("bootstrap-verified", wrongProfileCode: "ProfileMismatch")

        // Ordinary consumption deliberately does not use another Observation model.
        let subscription = try! engineOwner.subscribeState()
        ordinarySubscription = subscription
        ordinaryTask = Task { [weak self, subscription] in
            try await subscription.collect { [weak self] event in
                switch event {
                case .data(let snapshot): await self?.receiveOrdinary(snapshot)
                case .failure(let code): preconditionFailure("ordinary subscription failure: " + code)
                }
            }
        }
        record("owner-started")
    }

    func openPage() {
        precondition(!busy && displayedPage == nil && pages.isEmpty && !finished)
        let page = NativePageSession()
        pages[page.id] = page
        weakModels[page.id] = WeakNativeModel(page.model)
        createdPages += 1
        record("page-created", page)
        displayedPage = page
    }

    func appeared(_ page: NativePageSession) {
        guard !page.started else { preconditionFailure("unexpected repeated appearance") }
        page.started = true
        precondition(page.model.value == nil && page.model.status == .idle)
        try! page.model.start {
            pageFactories += 1
            return try makeMadBSkieStateSource(from: engineOwner)
        }
        precondition(page.model.value == nil, "new page invented initial replay")
        record("page-started", page)
    }

    func refresh(_ page: NativePageSession) {
        _ = page.model.value
        record("page-refreshed", page)
    }

    func duplicate(_ page: NativePageSession) {
        do {
            try page.model.start {
                pageFactories += 1
                return try makeMadBSkieStateSource(from: engineOwner)
            }
            preconditionFailure("duplicate registration admitted")
        } catch MadBObservationError.alreadyActive { record("duplicate-rejected", page, duplicateCode: "alreadyActive") }
        catch { preconditionFailure("unexpected duplicate error: \(error)") }
    }

    func publish(_ page: NativePageSession? = nil) {
        precondition(!busy && !finished && publishedIndex < Self.values.count)
        busy = true
        let value = Self.values[publishedIndex]
        publishedIndex += 1
        let previous = publicationTask
        publicationTask = Task { @MainActor in
            if let previous { await previous.value }
            try! engineOwner.native.publish(value: value.native())
            let deadline = ContinuousClock.now + .seconds(10)
            while !value.matches(ordinarySnapshot) || (page != nil && !value.matches(page?.model.value)) {
                precondition(ContinuousClock.now < deadline, "native state delivery timeout")
                await Task.yield()
            }
            await awaitQuiescent(subscriptions: page == nil ? 1 : 2, closed: false)
            if let page {
                precondition(page.model.collectionFailure == nil && page.model.stopFailure == nil)
            }
            record(page == nil ? "after-page-value" : "page-value", page)
            busy = false
        }
    }

    // Only the view hierarchy changes here; SwiftUI invokes onDisappear itself.
    func leavePage() {
        precondition(!busy && displayedPage != nil)
        busy = true
        displayedPage = nil
    }

    func disappeared(_ page: NativePageSession) {
        precondition(!page.stopping, "duplicate disappearance")
        page.stopping = true
        page.model.requestStop()
        record("page-disappeared", page)
        // Application ownership persists through the explicit drain confirmation.
        cleanupTasks[page.id] = Task { @MainActor in
            do {
                try await page.model.stopAndWait()
                precondition(page.model.status == .stopped && page.model.stopFailure == nil)
                await awaitQuiescent(subscriptions: 1, closed: false)
                drainedPages += 1
                record("page-drained", page)
                let id = page.id
                pages.removeValue(forKey: id)
                observeRelease(id)
            } catch { preconditionFailure("native page drain failed: \(error)") }
        }
    }

    func closeOwner() {
        precondition(!busy && displayedPage == nil && pages.isEmpty)
        precondition(createdPages == 3 && drainedPages == 3 && releasedPages == 3 && publishedIndex == 6)
        precondition(cleanupTasks.count == 3 && releaseTasks.count == 3)
        precondition(closeTask == nil)
        busy = true
        closeTask = Task { @MainActor in
            if let publicationTask { await publicationTask.value }
            publicationTask = nil
            // Retain every task handle through an explicit join; completed Void tasks
            // retain no page result and must not keep their finished captures alive.
            for task in cleanupTasks.values { await task.value }
            for task in releaseTasks.values { await task.value }
            cleanupTasks.removeAll()
            releaseTasks.removeAll()
            guard let subscription = ordinarySubscription, let task = ordinaryTask else {
                preconditionFailure("ordinary cleanup owner missing")
            }
            subscription.requestStop()
            try! await subscription.awaitStopped()
            try! await task.value
            ordinarySubscription = nil
            ordinaryTask = nil
            await awaitQuiescent(subscriptions: 0, closed: false)
            record("ordinary-drained")
            try! await engineOwner.awaitClosed()
            await awaitQuiescent(subscriptions: 0, closed: true)
            // No suspension or native cleanup follows this confirmation. MainActor
            // cannot dispatch Quit until this task finishes its synchronous tail.
            nativeCleanupConfirmed = true
            finished = true
            busy = false
            record("owner-closed")
        }
    }

    func applicationTerminated() {
        precondition(finished && nativeCleanupConfirmed && closeTask != nil,
                     "application terminated before explicit native close")
        precondition(publicationTask == nil && ordinaryTask == nil && ordinarySubscription == nil
                     && cleanupTasks.isEmpty && releaseTasks.isEmpty)
        record("application-terminated")
    }

    private func receiveOrdinary(_ snapshot: MadBValueSnapshot) {
        precondition(Thread.isMainThread)
        ordinarySnapshot = snapshot
        ordinaryDisplay = displayedSnapshot(snapshot)
        ordinaryDeliveries += 1
    }

    private func observeRelease(_ id: UUID) {
        releaseTasks[id] = Task { @MainActor in
            let deadline = ContinuousClock.now + .seconds(10)
            while weakModels[id]?.value != nil {
                precondition(ContinuousClock.now < deadline, "native page model retained after drain")
                await Task.yield()
            }
            releasedPages += 1
            record("model-release-observed", id: id)
            busy = false
        }
    }

    private func awaitQuiescent(subscriptions: Int, closed: Bool) async {
        let deadline = ContinuousClock.now + .seconds(10)
        while true {
            let stats = engineOwner.native.stats()
            if Int(stats.activeSubscriptions) == subscriptions && stats.activeOperations == 0
                && stats.queuedItems == 0 && stats.inflightItems == 0 && stats.retainedBytes == 0
                && stats.activeWaiters == 0 && stats.closed == closed { return }
            precondition(ContinuousClock.now < deadline, "native quiescence timeout")
            await Task.yield()
        }
    }

    private func snapshotJSON(_ snapshot: MadBValueSnapshot?) -> Any {
        guard let snapshot else { return NSNull() }
        return ["id": snapshot.id, "text": snapshot.text, "bytes": snapshot.bytes.map(Int.init),
                "sequence": snapshot.sequence.map { $0 as Any } ?? NSNull(),
                "phase": String(describing: snapshot.phase)] as [String: Any]
    }

    private func record(_ event: String, _ page: NativePageSession? = nil,
                        id: UUID? = nil, wrongProfileCode: String? = nil, duplicateCode: String? = nil) {
        let stats = engineOwner.native.stats()
        summary = "active=\(stats.activeSubscriptions) pages=\(createdPages) drained=\(drainedPages) released=\(releasedPages) factories=\(pageFactories) deliveries=\(ordinaryDeliveries) ordinary=\(ordinarySnapshot?.id ?? "nil") closed=\(stats.closed ? 1 : 0)"
        var row: [String: Any] = ["event": event, "nonce": nonce,
            "pid": ProcessInfo.processInfo.processIdentifier, "mainThread": Thread.isMainThread,
            "profile": profile, "interface": interface, "publishedIndex": publishedIndex,
            "createdPages": createdPages, "drainedPages": drainedPages, "releasedPages": releasedPages,
            "pageFactories": pageFactories, "ordinaryDeliveries": ordinaryDeliveries,
            "ordinarySnapshot": snapshotJSON(ordinarySnapshot), "pageSnapshot": snapshotJSON(page?.model.value),
            "pageID": (page?.id ?? id).map { $0.uuidString as Any } ?? NSNull(),
            "status": page.map { String(describing: $0.model.status) } as Any? ?? NSNull(),
            "native": ["activeSubscriptions": stats.activeSubscriptions, "activeOperations": stats.activeOperations,
                       "queuedItems": stats.queuedItems, "inflightItems": stats.inflightItems,
                       "retainedBytes": stats.retainedBytes, "activeWaiters": stats.activeWaiters,
                       "closed": stats.closed]]
        if let wrongProfileCode { row["wrongProfileCode"] = wrongProfileCode }
        if let duplicateCode { row["duplicateCode"] = duplicateCode }
        let bytes = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
        let handle = try! FileHandle(forWritingTo: logURL)
        try! handle.seekToEnd()
        try! handle.write(contentsOf: bytes + Data([10]))
        try! handle.synchronize()
        try! handle.close()
    }
}
