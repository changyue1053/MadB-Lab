import AppKit
import Darwin
import SwiftUI

@main @MainActor final class NativeAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow?
    private var owner: NativeApplicationOwner?

    func applicationDidFinishLaunching(_ notification: Notification) {
        writeProcessReceipt()
        let owner = NativeApplicationOwner()
        self.owner = owner
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 880, height: 600),
                              styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "MadB L04 Native SwiftUI"
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = NSHostingView(rootView: NativeRootView(owner: owner))
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { owner?.finished == true }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { owner?.applicationTerminated() }

    private func writeProcessReceipt() {
        let process = ProcessInfo.processInfo
        guard let nonce = process.environment["MADB_L04_NONCE"], !nonce.isEmpty,
              let path = process.environment["MADB_L04_LOG_PATH"], path.hasPrefix("/"),
              let executable = Bundle.main.executableURL?.resolvingSymlinksInPath().standardizedFileURL,
              executable.isFileURL, executable.path.hasPrefix("/") else {
            preconditionFailure("runner process identity inputs are missing")
        }
        let row: [String: Any] = ["nonce": nonce, "pid": process.processIdentifier,
                                  "executablePath": executable.path]
        let bytes = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
        // Establish process ownership before any native acquisition. Never replace
        // a receipt left by another launch, including a partial failed write.
        let descriptor = Darwin.open(path + ".process.json", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, mode_t(0o600))
        precondition(descriptor >= 0, "cannot exclusively create process receipt")
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        do {
            try handle.write(contentsOf: bytes + Data([10]))
            try handle.synchronize()
            try handle.close()
        } catch {
            try? handle.close()
            preconditionFailure("cannot preserve process receipt: \(error)")
        }
    }
}

private struct NativeRootView: View {
    let owner: NativeApplicationOwner
    var body: some View {
        VStack(spacing: 16) {
            Text("Public C06 SKIE candidate · macOS Arm64 · ordinary and page share one owner")
            Text(owner.summary).font(.system(size: 11, design: .monospaced)).accessibilityIdentifier("summary")
            Text(owner.ordinaryDisplay).font(.system(size: 11, design: .monospaced)).accessibilityIdentifier("ordinary-value")
            if let page = owner.displayedPage {
                NativeSwiftUIPage(page: page, owner: owner)
                    .id(page.id)
            } else {
                Button("Open SwiftUI page") { owner.openPage() }
                    .accessibilityIdentifier("open-swiftui").disabled(owner.busy || owner.finished)
                Button("Publish after page") { owner.publish() }
                    .accessibilityIdentifier("publish-after").disabled(owner.busy || owner.finished)
                Button("Close application owner") { owner.closeOwner() }
                    .accessibilityIdentifier("close-owner").disabled(owner.busy || owner.finished)
                Text(owner.finished ? "finished" : "running").accessibilityIdentifier("owner-state")
                Button("Quit after native close") {
                    precondition(owner.finished)
                    NSApplication.shared.terminate(nil)
                }.accessibilityIdentifier("quit").disabled(!owner.finished)
            }
        }.padding(24).frame(minWidth: 840, minHeight: 520)
    }
}

private struct NativeSwiftUIPage: View {
    let page: NativePageSession
    let owner: NativeApplicationOwner
    @State private var refreshes = 0

    var body: some View {
        VStack(spacing: 16) {
            Text(page.id.uuidString).accessibilityIdentifier("page-id")
            Text(displayedSnapshot(page.model.value)).font(.system(size: 12, design: .monospaced))
                .accessibilityIdentifier("page-value")
            Text("refreshes=\(refreshes)").accessibilityIdentifier("refresh-count")
            Button("Refresh/getter") { refreshes += 1; owner.refresh(page) }
                .accessibilityIdentifier("refresh").disabled(owner.busy)
            Button("Duplicate start") { owner.duplicate(page) }
                .accessibilityIdentifier("duplicate").disabled(owner.busy)
            Button("Publish") { owner.publish(page) }
                .accessibilityIdentifier("publish").disabled(owner.busy)
            Button("Close page") { owner.leavePage() }
                .accessibilityIdentifier("close-page").disabled(owner.busy)
        }
        .onAppear { owner.appeared(page) }
        .onDisappear { owner.disappeared(page) }
    }
}
