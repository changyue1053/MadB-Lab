import XCTest

@MainActor final class LifecycleUITests: XCTestCase {
    private func equal(_ element: XCUIElement, _ expected: String,
                       file: StaticString = #filePath, line: UInt = #line) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", expected), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 15), .completed, file: file, line: line)
    }

    private func summary(_ app: XCUIApplication, active: Int, pages: Int, drained: Int,
                         released: Int, factories: Int, deliveries: Int, ordinary: String, closed: Int = 0) {
        equal(app.staticTexts["summary"], "active=\(active) pages=\(pages) drained=\(drained) released=\(released) factories=\(factories) deliveries=\(deliveries) ordinary=\(ordinary) closed=\(closed)")
    }

    func testNativeSwiftUILifecycleAndSharedOrdinaryOwner() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        addTeardownBlock { @MainActor in
            // Emergency process cleanup is not a substitute for the explicit close assertions.
            if app.state != .notRunning { app.terminate() }
        }
        app.launchEnvironment["MADB_L04_NONCE"] = "__NONCE__"
        app.launchEnvironment["MADB_L04_PROFILE"] = "__PROFILE__"
        app.launchEnvironment["MADB_L04_INTERFACE"] = "__INTERFACE__"
        app.launchEnvironment["MADB_L04_LOG_PATH"] = "__LOG_PATH__"
        app.launch()
        summary(app, active: 1, pages: 0, drained: 0, released: 0, factories: 0, deliveries: 0, ordinary: "nil")
        equal(app.staticTexts["ordinary-value"], "nil")

        // Literal independent expectations; do not import the app's value table or native implementation.
        let pageValues = ["ascii|6e61746976652070616765206f6e65|007f80ff",
                          "unicode|e4bda0e5a5bdc3a9f09f9982|00c3a9ff",
                          "nul|6c656674007269676874|"]
        let afterValues = ["after-1|6166746572206f6e65|ff00",
                           "after-2|e9a1b5e99da2e98080e587bae5908e|8001",
                           "after-3||00"]
        let pageIDs = ["ascii", "unicode", "nul"]
        var identities = Set<String>()
        for index in 0..<3 {
            let round = index + 1
            app.buttons["open-swiftui"].click()
            XCTAssertTrue(app.staticTexts["page-id"].waitForExistence(timeout: 15))
            let identity = try XCTUnwrap(app.staticTexts["page-id"].value as? String)
            XCTAssertNotNil(UUID(uuidString: identity))
            XCTAssertTrue(identities.insert(identity).inserted)
            equal(app.staticTexts["page-value"], "nil")
            summary(app, active: 2, pages: round, drained: index, released: index,
                    factories: round, deliveries: index * 2, ordinary: index == 0 ? "nil" : "after-\(index)")
            app.buttons["refresh"].click()
            equal(app.staticTexts["refresh-count"], "refreshes=1")
            equal(app.staticTexts["page-id"], identity)
            app.buttons["duplicate"].click()
            summary(app, active: 2, pages: round, drained: index, released: index,
                    factories: round, deliveries: index * 2, ordinary: index == 0 ? "nil" : "after-\(index)")
            app.buttons["publish"].click()
            equal(app.staticTexts["page-value"], pageValues[index])
            equal(app.staticTexts["ordinary-value"], pageValues[index])
            summary(app, active: 2, pages: round, drained: index, released: index,
                    factories: round, deliveries: index * 2 + 1, ordinary: pageIDs[index])
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "native-swiftui-page-\(round)"; screenshot.lifetime = .keepAlways; add(screenshot)
            app.buttons["close-page"].click()
            XCTAssertTrue(app.buttons["open-swiftui"].waitForExistence(timeout: 15))
            summary(app, active: 1, pages: round, drained: round, released: round,
                    factories: round, deliveries: index * 2 + 1, ordinary: pageIDs[index])
            app.buttons["publish-after"].click()
            equal(app.staticTexts["ordinary-value"], afterValues[index])
            summary(app, active: 1, pages: round, drained: round, released: round,
                    factories: round, deliveries: round * 2, ordinary: "after-\(round)")
        }
        app.buttons["close-owner"].click()
        equal(app.staticTexts["owner-state"], "finished")
        summary(app, active: 0, pages: 3, drained: 3, released: 3, factories: 3,
                deliveries: 6, ordinary: "after-3", closed: 1)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "native-owner-closed"; screenshot.lifetime = .keepAlways; add(screenshot)
        app.buttons["quit"].click()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 15), "normal exit after native close was not observed")
    }
}
