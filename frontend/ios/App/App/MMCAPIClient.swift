import Capacitor
import Foundation

/// The MMC HTTP client (ADR 0029): session state and every call to the MMC
/// backend, held here so the access token never crosses the WebView bridge.
///
/// Deliberately knows nothing about Apple Music or MusicKit -- `MMCMusicPlugin`
/// owns that half and hands this client only what an MMC API call actually
/// needs (a Music User Token as a plain string, a mix id). Split out of the
/// plugin itself so the plugin's own class body stays about being a Capacitor
/// plugin, not about being an HTTP client too.
@MainActor
final class MMCAPIClient {
    // Lives for the life of the process and is never written to disk, the
    // keychain, or the WebView.
    private var apiBaseURL: URL?
    private var accessToken: String?
    private var displayName: String?
    private var accountEmail: String?

    var isSignedIn: Bool { accessToken != nil }

    func sessionPayload() -> JSObject {
        guard accessToken != nil else { return ["signedIn": false] }
        return [
            "signedIn": true,
            "displayName": displayName ?? "",
            "email": accountEmail ?? ""
        ]
    }

    func signIn(apiBaseUrl: String, email: String, password: String) async throws -> JSObject {
        guard let base = Self.normalizedBaseURL(apiBaseUrl) else {
            throw ProofError.invalidBaseURL
        }
        guard !email.isEmpty, !password.isEmpty else {
            throw ProofError.credentialsRequired
        }
        // Clear any previous identity first, so a failed account switch cannot
        // leave the old session live behind a new name.
        clearSession()
        apiBaseURL = base

        let login = try await send(
            path: "/api/v1/auth/login",
            method: "POST",
            body: ["email": email, "password": password],
            authorized: false,
            // The backend answers one uniform 401 for wrong password, unknown
            // email and no-password-set. Do not say more than it did.
            unauthorized: { _ in "INVALID_CREDENTIALS" }
        )
        guard let token = login["access_token"] as? String, !token.isEmpty else {
            throw ProofError.badResponse
        }
        accessToken = token

        let profile = try await send(path: "/api/v1/users/me", method: "GET")
        displayName = profile["display_name"] as? String
        accountEmail = profile["email"] as? String
        return sessionPayload()
    }

    func signOut() async -> JSObject {
        if accessToken != nil {
            // Best effort: a server that refuses the call must not strand the
            // app in a session the member has already left.
            _ = try? await send(path: "/api/v1/auth/logout", method: "POST")
        }
        clearSession()
        return sessionPayload()
    }

    /// Drop every trace of the signed-in member, refresh cookie included. The
    /// cookie lives in the shared store because `URLSession.shared` puts it
    /// there, so clearing the token alone would leave it behind.
    func clearSession() {
        accessToken = nil
        displayName = nil
        accountEmail = nil
        if let host = apiBaseURL?.host, let cookies = HTTPCookieStorage.shared.cookies {
            for cookie in cookies {
                // A cookie set for ".example.com" covers "api.example.com", so
                // compare both directions rather than only suffix-matching one.
                let domain = cookie.domain.hasPrefix(".")
                    ? String(cookie.domain.dropFirst())
                    : cookie.domain
                if host == domain || host.hasSuffix("." + domain) || domain.hasSuffix("." + host) {
                    HTTPCookieStorage.shared.deleteCookie(cookie)
                }
            }
        }
        apiBaseURL = nil
    }

    func getApplePlaylistRecord(mixId: UUID) async throws -> [String: Any] {
        try await send(path: "/api/v1/mixes/\(mixId.uuidString.lowercased())/apple-playlist", method: "GET")
    }

    func createApplePlaylist(
        mixId: UUID,
        musicUserToken: String,
        tzOffsetMinutes: Int?
    ) async throws -> [String: Any] {
        var body: [String: Any] = ["music_user_token": musicUserToken]
        if let tzOffsetMinutes { body["tz_offset_minutes"] = tzOffsetMinutes }
        return try await send(
            path: "/api/v1/mixes/\(mixId.uuidString.lowercased())/apple-playlist",
            method: "POST",
            body: body,
            unauthorized: Self.playlistUnauthorizedCode
        )
    }

    // MARK: - HTTP

    /// Accept what a person would type into the field: with or without a scheme,
    /// with or without a trailing slash. Anything that is not http(s) is refused
    /// rather than guessed at.
    private static func normalizedBaseURL(_ raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        while text.hasSuffix("/") { text.removeLast() }
        if !text.contains("://") { text = "https://" + text }
        guard let url = URL(string: text),
              let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http",
              url.host != nil
        else { return nil }
        return url
    }

    @discardableResult
    private func send(
        path: String,
        method: String,
        body: [String: Any]? = nil,
        authorized: Bool = true,
        unauthorized: (String?) -> String = { _ in "SESSION_EXPIRED" }
    ) async throws -> [String: Any] {
        guard let base = apiBaseURL, let url = URL(string: base.absoluteString + path) else {
            throw ProofError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if authorized {
            guard let token = accessToken else { throw ProofError.notSignedIn }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            // Reachability, TLS, and cancellation all land here. The category is
            // all the UI needs, and the underlying description can name the host.
            throw ProofError.network
        }
        guard let http = response as? HTTPURLResponse else { throw ProofError.badResponse }

        let parsed = try? JSONSerialization.jsonObject(with: data)
        let payload = parsed as? [String: Any] ?? [:]
        guard (200..<300).contains(http.statusCode) else {
            let detail = payload["detail"] as? String
            throw ProofError.server(
                Self.serverCode(http.statusCode, detail: detail, unauthorized: unauthorized)
            )
        }
        return payload
    }

    /// What a 401 from the playlist endpoint means.
    ///
    /// This is the fragile one: `POST /mixes/{id}/apple-playlist` answers 401
    /// both for an expired MMC session and for an expired Music User Token, and
    /// the only discriminator on the wire is the detail string
    /// (MysteryMixClub-6x45). Match the narrow, documented neutral constant for
    /// the session case and let every other 401 mean Apple, so an unrecognised
    /// one prompts a reconnect rather than dropping a live session.
    private static let playlistUnauthorizedCode: (String?) -> String = { detail in
        detail == "not authenticated" ? "SESSION_EXPIRED" : "APPLE_AUTH_EXPIRED"
    }

    /// Map a server status onto something the UI can act on. Callers own the
    /// 401 meaning, because it differs by endpoint.
    private static func serverCode(
        _ status: Int,
        detail: String?,
        unauthorized: (String?) -> String
    ) -> String {
        switch status {
        case 401: return unauthorized(detail)
        case 403: return "NOT_A_MEMBER"
        case 404: return "MIX_NOT_FOUND"
        case 422: return "REQUEST_REJECTED"
        case 429: return "RATE_LIMITED"
        case 502: return "APPLE_SERVICE_ERROR"
        case 503: return "APPLE_NOT_CONFIGURED"
        default: return "SERVER_ERROR"
        }
    }
}
