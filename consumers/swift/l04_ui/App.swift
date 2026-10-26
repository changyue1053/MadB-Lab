import UIKit
import SwiftUI
import Observation

@main @MainActor final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    private var owner: ApplicationOwner?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let owner = ApplicationOwner()
        self.owner = owner
        let navigation = UINavigationController()
        let root = UIHostingController(rootView: RootView(owner: owner) { [weak navigation] framework in
            let page = owner.makePage(framework)
            let controller: UIViewController = framework == "swiftui"
                ? SwiftUIPageController(page: page, owner: owner)
                : UIKitPageController(page: page, owner: owner)
            navigation?.pushViewController(controller, animated: false)
        })
        root.title = "MadB L04 independent UI"
        navigation.setViewControllers([root], animated: false)
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = navigation
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}

private struct RootView: View {
    let owner: ApplicationOwner
    let open: (String) -> Void
    var body: some View {
        VStack(spacing: 20) {
            Text("Pure Swift source; no native composition")
            Text(owner.summary).accessibilityIdentifier("summary")
            Button("Open SwiftUI") { open("swiftui") }.accessibilityIdentifier("open-swiftui")
            Button("Open UIKit") { open("uikit") }.accessibilityIdentifier("open-uikit")
            Button("Publish after page") { owner.publish() }.accessibilityIdentifier("publish-after")
            Button("Close application owner") { owner.closeOwner() }.accessibilityIdentifier("close-owner")
            Text(owner.finished ? "finished" : "running").accessibilityIdentifier("owner-state")
        }.padding()
    }
}

private struct SwiftUIPage: View {
    let page: PageSession
    let owner: ApplicationOwner
    let close: () -> Void
    @State private var refreshes = 0
    var body: some View {
        VStack(spacing: 16) {
            Text(page.id.uuidString).accessibilityIdentifier("page-id")
            Text(String(page.model.value ?? -1)).accessibilityIdentifier("page-value")
            Text(owner.summary).accessibilityIdentifier("summary")
            Text("refreshes=\(refreshes)")
            Button("Publish") { owner.publish(page) }.accessibilityIdentifier("publish")
            Button("Refresh/getter") { refreshes += 1; owner.refresh(page) }.accessibilityIdentifier("refresh")
            Button("Duplicate start") { owner.duplicate(page) }.accessibilityIdentifier("duplicate")
            Button("Close page") { close() }.accessibilityIdentifier("close-page")
        }
        .padding()
        .onAppear { owner.appeared(page) }
        .onDisappear { owner.disappeared(page) }
    }
}

@MainActor private final class SwiftUIPageController: UIHostingController<SwiftUIPage> {
    private let page: PageSession
    private let owner: ApplicationOwner
    init(page: PageSession, owner: ApplicationOwner) {
        self.page = page; self.owner = owner
        super.init(rootView: SwiftUIPage(page: page, owner: owner, close: {}))
        rootView = SwiftUIPage(page: page, owner: owner) { [weak self] in
            self?.navigationController?.popViewController(animated: false)
        }
        title = "SwiftUI page"
    }
    @MainActor required dynamic init?(coder: NSCoder) { fatalError("not a storyboard app") }
    deinit {
        let owner = owner, id = page.id, framework = page.framework
        Task { @MainActor in owner.controllerDestroyed(id, framework: framework) }
    }
}

@MainActor private final class UIKitPageController: UIViewController {
    private let page: PageSession
    private let owner: ApplicationOwner
    private let valueLabel = UILabel()
    private let summaryLabel = UILabel()
    init(page: PageSession, owner: ApplicationOwner) {
        self.page = page; self.owner = owner
        super.init(nibName: nil, bundle: nil)
        title = "UIKit page"
    }
    @MainActor required init?(coder: NSCoder) { fatalError("not a storyboard app") }
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        let identity = UILabel(); identity.text = page.id.uuidString; identity.accessibilityIdentifier = "page-id"
        valueLabel.accessibilityIdentifier = "page-value"
        summaryLabel.accessibilityIdentifier = "summary"; summaryLabel.numberOfLines = 0
        let stack = UIStackView(arrangedSubviews: [identity, valueLabel, summaryLabel])
        stack.axis = .vertical; stack.spacing = 20; stack.translatesAutoresizingMaskIntoConstraints = false
        func button(_ label: String, _ id: String, _ operation: @escaping @MainActor () -> Void) {
            let button = UIButton(type: .system); button.setTitle(label, for: .normal)
            button.accessibilityIdentifier = id
            button.addAction(UIAction { _ in operation() }, for: .touchUpInside)
            stack.addArrangedSubview(button)
        }
        button("Publish", "publish") { [owner, page] in owner.publish(page) }
        button("Refresh/getter", "refresh") { [weak self] in
            guard let self else { return }; owner.refresh(page); updateLabels()
        }
        button("Duplicate start", "duplicate") { [owner, page] in owner.duplicate(page) }
        button("Close page", "close-page") { [weak self] in self?.navigationController?.popViewController(animated: false) }
        view.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            stack.centerYAnchor.constraint(equalTo: view.safeAreaLayoutGuide.centerYAnchor)])
        updateLabels()
    }
    override func viewDidAppear(_ animated: Bool) { super.viewDidAppear(animated); owner.appeared(page) }
    override func viewWillDisappear(_ animated: Bool) { owner.disappeared(page); super.viewWillDisappear(animated) }
    private func updateLabels() {
        withObservationTracking {
            valueLabel.text = String(page.model.value ?? -1)
            summaryLabel.text = owner.summary
        } onChange: { [weak self] in Task { @MainActor in self?.updateLabels() } }
    }
    deinit {
        let owner = owner, id = page.id, framework = page.framework
        Task { @MainActor in owner.controllerDestroyed(id, framework: framework) }
    }
}
