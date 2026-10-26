import XCTest

@MainActor final class LifecycleUITests: XCTestCase {
    private func equal(_ element: XCUIElement, _ expected: String, file: StaticString = #filePath, line: UInt = #line) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", expected), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 10), .completed, file: file, line: line)
    }
    private func summary(_ app: XCUIApplication, active: Int, created: Int, drained: Int,
                         destroyed: Int, released: Int, value: Int, closed: Int = 0) {
        equal(app.staticTexts["summary"], "active=\(active) created=\(created) drained=\(drained) destroyed=\(destroyed) released=\(released) ordinary=\(value) sourceClosed=\(closed)")
    }
    func testActualNavigationAndSharedSource() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["MADB_L04_NONCE"] = "__NONCE__"
        app.launch()
        summary(app, active: 1, created: 1, drained: 0, destroyed: 0, released: 0, value: -1)
        var identities = Set<String>()
        var round = 0
        for framework in ["swiftui", "uikit"] {
            for _ in 0..<3 {
                round += 1
                app.buttons["open-" + framework].tap()
                XCTAssertTrue(app.staticTexts["page-id"].waitForExistence(timeout: 10))
                let identity = app.staticTexts["page-id"].label
                XCTAssertNotNil(UUID(uuidString: identity)); XCTAssertTrue(identities.insert(identity).inserted)
                equal(app.staticTexts["page-value"], "-1")
                summary(app, active: 2, created: round + 1, drained: round - 1, destroyed: round - 1, released: round - 1,
                        value: round == 1 ? -1 : (round - 1) * 2)
                app.buttons["refresh"].tap()
                equal(app.staticTexts["page-id"], identity)
                app.buttons["duplicate"].tap()
                app.buttons["publish"].tap()
                equal(app.staticTexts["page-value"], String(round * 2 - 1))
                summary(app, active: 2, created: round + 1, drained: round - 1, destroyed: round - 1,
                        released: round - 1, value: round * 2 - 1)
                let screenshot = XCTAttachment(screenshot: app.screenshot())
                screenshot.name = framework + "-page-" + String(round); screenshot.lifetime = .keepAlways; add(screenshot)
                app.buttons["close-page"].tap()
                XCTAssertTrue(app.buttons["open-" + framework].waitForExistence(timeout: 10))
                summary(app, active: 1, created: round + 1, drained: round, destroyed: round,
                        released: round, value: round * 2 - 1)
                app.buttons["publish-after"].tap()
                summary(app, active: 1, created: round + 1, drained: round, destroyed: round,
                        released: round, value: round * 2)
            }
        }
        app.buttons["close-owner"].tap()
        equal(app.staticTexts["owner-state"], "finished")
        summary(app, active: 0, created: 7, drained: 7, destroyed: 6, released: 6, value: 12, closed: 1)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "owner-closed"; screenshot.lifetime = .keepAlways; add(screenshot)
    }
}
