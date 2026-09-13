import Capacitor
import XCTest
@testable import App

/// Covers the session-refresh path added for MysteryMixClub-mfhg.1 and the
/// structured-401 discrimination fixed for MysteryMixClub-6x45. Both live in
/// `MMCAPIClient.send()`, so they share one fixture: `MockURLProtocol` stubs
/// stand in for the MMC backend, keyed by exact request path.
@MainActor
final class MMCAPIClientTests: XCTestCase {
    private var api: MMCAPIClient!
    private let mixId = UUID(uuidString: "11111111-1111-1111-1111-111111111111")!

    override func setUp() {
        super.setUp()
        URLProtocol.registerClass(MockURLProtocol.self)
        api = MMCAPIClient()
    }

    override func tearDown() {
        URLProtocol.unregisterClass(MockURLProtocol.self)
        MockURLProtocol.reset()
        api = nil
        super.tearDown()
    }

    private func stub(_ path: String, status: Int, json: [String: Any]) {
        MockURLProtocol.stubs[path, default: []].append(.init(status: status, json: json))
    }

    private func refreshRequestCount() -> Int {
        MockURLProtocol.requests.filter { $0.url?.path == "/api/v1/auth/refresh" }.count
    }

    private func signIn() async throws {
        stub("/api/v1/auth/login", status: 200, json: ["access_token": "token-1", "token_type": "bearer"])
        stub("/api/v1/users/me", status: 200, json: ["display_name": "Dawn", "email": "dawn@example.com"])
        _ = try await api.signIn(apiBaseUrl: "https://mmc.test", email: "dawn@example.com", password: "hunter2")
    }

    func test_sessionExpired401_refreshesAndRetriesTransparently() async throws {
        try await signIn()
        let path = "/api/v1/mixes/\(mixId.uuidString.lowercased())/apple-playlist"
        stub(path, status: 401, json: ["detail": "not authenticated"])
        stub("/api/v1/auth/refresh", status: 200, json: ["access_token": "token-2", "token_type": "bearer"])
        stub(path, status: 200, json: ["playlist_name": "Mix Vol. 1"])

        let result = try await api.getApplePlaylistRecord(mixId: mixId)

        XCTAssertEqual(result["playlist_name"] as? String, "Mix Vol. 1")
        XCTAssertEqual(refreshRequestCount(), 1)
    }

    func test_failedRefresh_clearsSessionAndSurfacesSessionExpired_withoutLooping() async throws {
        try await signIn()
        let path = "/api/v1/mixes/\(mixId.uuidString.lowercased())/apple-playlist"
        stub(path, status: 401, json: ["detail": "not authenticated"])
        // The refresh cookie itself is invalid/expired -- e.g. logout-all ran
        // server-side. Exactly one refresh attempt should follow, never a
        // second, and the session should not be left half-signed-in.
        stub("/api/v1/auth/refresh", status: 401, json: ["detail": "not authenticated"])

        do {
            _ = try await api.getApplePlaylistRecord(mixId: mixId)
            XCTFail("expected ProofError.server(\"SESSION_EXPIRED\")")
        } catch ProofError.server(let code) {
            XCTAssertEqual(code, "SESSION_EXPIRED")
        }

        XCTAssertFalse(api.isSignedIn)
        XCTAssertEqual(refreshRequestCount(), 1)
    }

    func test_appleAuthExpired401_doesNotTriggerARefresh() async throws {
        try await signIn()
        let path = "/api/v1/mixes/\(mixId.uuidString.lowercased())/apple-playlist"
        // The structured code (MysteryMixClub-6x45) means the MMC session is
        // fine and only the Apple side is stale -- refreshing an already-valid
        // access token would not fix anything, so it must not be attempted.
        stub(
            path, status: 401,
            json: ["detail": ["message": "apple music authorization expired; reconnect and try again",
                               "code": "apple_auth_expired"]]
        )

        do {
            _ = try await api.createApplePlaylist(mixId: mixId, musicUserToken: "mut", tzOffsetMinutes: nil)
            XCTFail("expected ProofError.server(\"APPLE_AUTH_EXPIRED\")")
        } catch ProofError.server(let code) {
            XCTAssertEqual(code, "APPLE_AUTH_EXPIRED")
        }

        XCTAssertTrue(api.isSignedIn, "an Apple-only failure must not drop the MMC session")
        XCTAssertEqual(refreshRequestCount(), 0)
    }
}
