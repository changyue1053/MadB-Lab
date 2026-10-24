import Foundation
import MadBSkie

@main
struct C06SkieConsumer {
    @MainActor
    static func main() async {
        do {
            guard CommandLine.arguments.count == 3 else {
                throw LabFailure(description: "usage: consumer CASE EXPECTED_PROFILE")
            }
            let scenario = CommandLine.arguments[1]
            let profile = CommandLine.arguments[2]
            switch scenario {
            case "data": try await dataCase(profile)
            case "errors": try await errorsCase(profile)
            case "objects": try await objectsCase(profile)
            case "async": try await asyncCase(profile)
            case "cancel": try await cancelCase(profile)
            case "late-callback": try await lateCallbackCase(profile)
            case "capacity": try await capacityCase(profile)
            case "shutdown": try await shutdownCase(profile)
            case "identity", "distribution": try await identityCase(profile)
            case "wrong-profile": try wrongProfileCase(profile)
            case "enhanced-api": try await enhancedAPICase(profile)
            default: throw LabFailure(description: "unsupported consumer scenario: \(scenario)")
            }
            print("{\"result\":\"passed\"}")
        } catch {
            FileHandle.standardError.write(Data("C06 Swift/SKIE failed: \(error)\n".utf8))
            exit(1)
        }
    }
}
