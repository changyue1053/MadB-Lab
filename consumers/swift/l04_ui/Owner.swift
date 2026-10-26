import Foundation
import MadBObservation
import Observation

@MainActor final class PageSession {
    let id = UUID()
    let framework: String
    let model = MadBStateModel<Int>()
    var started = false
    var stopping = false
    init(_ framework: String) { self.framework = framework }
}

@MainActor private final class WeakModel {
    weak var value: MadBStateModel<Int>?
    init(_ value: MadBStateModel<Int>) { self.value = value }
}

@MainActor @Observable final class ApplicationOwner {
    let hub = LocalStateHub()
    let ordinary = MadBStateModel<Int>()
    var summary = "starting"
    var finished = false
    private var value = 0
    private var pages: [UUID: PageSession] = [:]
    private var weakModels: [UUID: WeakModel] = [:]
    private var destroyed = 0
    private var pageCount = 0
    private let nonce: String
    private let logURL: URL

    init() {
        nonce = ProcessInfo.processInfo.environment["MADB_L04_NONCE"] ?? "missing"
        precondition(nonce != "missing")
        logURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("l04-evidence.jsonl")
        precondition(!FileManager.default.fileExists(atPath: logURL.path))
        precondition(FileManager.default.createFile(atPath: logURL.path, contents: Data()))
        try! ordinary.start { hub.subscribe() }
        record("owner-started")
    }

    func makePage(_ framework: String) -> PageSession {
        let page = PageSession(framework)
        pages[page.id] = page
        weakModels[page.id] = WeakModel(page.model)
        pageCount += 1
        record("page-created", page)
        return page
    }

    func appeared(_ page: PageSession) {
        guard !page.started else { record("page-reappeared", page); return }
        page.started = true
        try! page.model.start { hub.subscribe() }
        record("page-started", page)
    }

    func refresh(_ page: PageSession) { _ = page.model.value; record("page-refreshed", page) }

    func duplicate(_ page: PageSession) {
        do {
            try page.model.start { hub.subscribe() }
            preconditionFailure("duplicate registration admitted")
        } catch MadBObservationError.alreadyActive { record("duplicate-rejected", page) }
        catch { preconditionFailure("unexpected duplicate error") }
    }

    func publish(_ page: PageSession? = nil) {
        value += 1
        let sent = value
        hub.publish(sent)
        Task { @MainActor in
            let deadline = ContinuousClock.now + .seconds(5)
            while ordinary.value != sent || (page != nil && page?.model.value != sent) {
                precondition(ContinuousClock.now < deadline, "state delivery timeout")
                await Task.yield()
            }
            record(page == nil ? "after-page-value" : "page-value", page)
        }
    }

    func disappeared(_ page: PageSession) {
        guard !page.stopping else { return }
        page.stopping = true
        page.model.requestStop()
        record("page-disappeared", page)
        // The application cleanup owner retains the session until drain succeeds.
        Task { @MainActor in
            do {
                try await page.model.stopAndWait()
                record("page-drained", page)
                pages.removeValue(forKey: page.id)
                update()
            } catch { preconditionFailure("page drain failed: \(error)") }
        }
    }

    func controllerDestroyed(_ id: UUID, framework: String) {
        destroyed += 1
        record("controller-destroyed", id: id.uuidString, framework: framework)
        // Observe ARC release separately from disappearance and source drain.
        Task { @MainActor in
            let deadline = ContinuousClock.now + .seconds(5)
            while weakModels[id]?.value != nil {
                precondition(ContinuousClock.now < deadline, "page model retained after cleanup")
                await Task.yield()
            }
            record("model-release-observed", id: id.uuidString, framework: framework)
        }
    }

    func closeOwner() {
        Task { @MainActor in
            precondition(pages.isEmpty)
            try! await ordinary.stopAndWait()
            hub.close()
            finished = true
            record("owner-closed")
        }
    }

    private func update() {
        let c = hub.counts()
        let released = weakModels.values.filter { $0.value == nil }.count
        summary = "active=\(c["active"]!) created=\(c["created"]!) drained=\(c["drained"]!) destroyed=\(destroyed) released=\(released) ordinary=\(ordinary.value ?? -1) sourceClosed=\(c["sourceClosed"]!)"
    }

    private func record(_ event: String, _ page: PageSession? = nil, id: String? = nil, framework: String? = nil) {
        update()
        var row: [String: Any] = ["event": event, "nonce": nonce,
            "pid": ProcessInfo.processInfo.processIdentifier, "counts": hub.counts(),
            "pageCount": pageCount, "destroyed": destroyed,
            "released": weakModels.values.filter { $0.value == nil }.count,
            "ordinaryValue": ordinary.value ?? -1, "published": value,
            "mainThread": Thread.isMainThread]
        if let page { row["pageID"] = page.id.uuidString; row["framework"] = page.framework
            row["pageValue"] = page.model.value ?? -1; row["status"] = String(describing: page.model.status) }
        if let id { row["pageID"] = id }
        if let framework { row["framework"] = framework }
        let bytes = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
        let handle = try! FileHandle(forWritingTo: logURL)
        try! handle.seekToEnd(); try! handle.write(contentsOf: bytes + Data([10])); try! handle.close()
    }
}
