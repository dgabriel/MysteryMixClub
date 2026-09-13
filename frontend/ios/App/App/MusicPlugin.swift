import Capacitor
import MusicKit
import UIKit

/// The proof's whole native surface: Apple Music authorization, the MMC session,
/// and playlist creation (ADR 0028, ADR 0029).
///
/// Two credentials exist in this app and **neither crosses the bridge**: Apple's
/// Music User Token, and the MMC access token. Both are held here and spent here;
/// JavaScript receives outcomes only. That is why the server calls live in Swift
/// rather than reusing `frontend/src/services/api.ts` -- see ADR 0029 for the
/// full reasoning, including the CORS and refresh-cookie consequences that made
/// the reuse path worse than it looks.
@objc(MMCMusicPlugin)
public final class MMCMusicPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MMCMusicPlugin"
    public let jsName = "MMCMusic"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "status", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "authorize", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "inspect", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "signIn", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "sessionStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "signOut", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "createPlaylist", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "reconcile", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openMusic", returnType: CAPPluginReturnPromise)
    ]

    /// Apple Music's Library. Deliberately not a direct playlist link: a library
    /// playlist URL does not resolve on a mobile client, confirmed twice on a
    /// real device including through the native `music://` scheme
    /// (MysteryMixClub-o3r8, MysteryMixClub-ap25). The member is sent to their
    /// library and told the playlist name instead.
    private static let libraryURL = URL(string: "https://music.apple.com/library")!

    /// Apple's own calls are user-paced but local. A playlist build is a server
    /// round trip that resolves every track against Apple's catalog, so it gets
    /// materially longer before we call it unanswered.
    private static let defaultTimeout: UInt64 = 30_000_000_000
    private static let playlistTimeout: UInt64 = 120_000_000_000

    // All access is confined to the main actor, including promise settlement.
    @MainActor private var busy = false

    // MMC session state. Lives for the life of the process and is never written
    // to disk, the keychain, or the WebView.
    @MainActor private var apiBaseURL: URL?
    @MainActor private var accessToken: String?
    @MainActor private var displayName: String?
    @MainActor private var accountEmail: String?

    private func authorizationName() -> String {
        switch MusicAuthorization.currentStatus {
        case .notDetermined: return "notDetermined"
        case .authorized: return "authorized"
        case .denied: return "denied"
        case .restricted: return "restricted"
        @unknown default: return "unknown"
        }
    }

    // MARK: - Apple Music authorization

    @objc func status(_ call: CAPPluginCall) {
        call.resolve(["authorization": authorizationName()])
    }

    @objc func authorize(_ call: CAPPluginCall) {
        Task { @MainActor in
            self.run(call) {
                if MusicAuthorization.currentStatus == .notDetermined {
                    _ = await MusicAuthorization.request()
                }
                return ["authorization": self.authorizationName()]
            }
        }
    }

    @objc func inspect(_ call: CAPPluginCall) {
        Task { @MainActor in
            self.run(call) {
                guard MusicAuthorization.currentStatus == .authorized else {
                    throw ProofError.permissionRequired
                }
                let subscription = try await MusicSubscription.current
                var tokenAvailable = false
                if subscription.canPlayCatalogContent && subscription.hasCloudLibraryEnabled {
                    _ = try await self.musicUserToken()
                    tokenAvailable = true
                }
                guard MusicAuthorization.currentStatus == .authorized else {
                    throw ProofError.permissionRequired
                }
                // Never return tokens through the WebView bridge or log them.
                // This tests Apple's native provider, not MMC server compatibility.
                return [
                    "authorization": self.authorizationName(),
                    "canPlayCatalogContent": subscription.canPlayCatalogContent,
                    "hasCloudLibraryEnabled": subscription.hasCloudLibraryEnabled,
                    "tokenAvailable": tokenAvailable
                ]
            }
        }
    }

    /// A fresh Music User Token. The return value never leaves this file's call
    /// stack; callers spend it on a request and discard it.
    @MainActor private func musicUserToken() async throws -> String {
        let provider = MusicDataRequest.tokenProvider
        let developerToken = try await provider.developerToken(options: [])
        let userToken = try await provider.userToken(for: developerToken, options: [])
        guard !userToken.isEmpty else { throw ProofError.tokenUnavailable }
        return userToken
    }

    // MARK: - MMC session

    @objc func sessionStatus(_ call: CAPPluginCall) {
        Task { @MainActor in
            call.resolve(self.sessionPayload())
        }
    }

    @MainActor private func sessionPayload() -> JSObject {
        guard accessToken != nil else { return ["signedIn": false] }
        return [
            "signedIn": true,
            "displayName": displayName ?? "",
            "email": accountEmail ?? ""
        ]
    }

    @objc func signIn(_ call: CAPPluginCall) {
        let baseURL = call.getString("apiBaseUrl") ?? ""
        let email = call.getString("email") ?? ""
        let password = call.getString("password") ?? ""
        Task { @MainActor in
            self.run(call) {
                guard let base = Self.normalizedBaseURL(baseURL) else {
                    throw ProofError.invalidBaseURL
                }
                guard !email.isEmpty, !password.isEmpty else {
                    throw ProofError.credentialsRequired
                }
                // Clear any previous identity first, so a failed account switch
                // cannot leave the old session live behind a new name.
                self.clearSession()
                self.apiBaseURL = base

                let login = try await self.send(
                    path: "/api/v1/auth/login",
                    method: "POST",
                    body: ["email": email, "password": password],
                    authorized: false,
                    // The backend answers one uniform 401 for wrong password,
                    // unknown email and no-password-set. Do not say more than it did.
                    unauthorized: { _ in "INVALID_CREDENTIALS" }
                )
                guard let token = login["access_token"] as? String, !token.isEmpty else {
                    throw ProofError.badResponse
                }
                self.accessToken = token

                let profile = try await self.send(path: "/api/v1/users/me", method: "GET")
                self.displayName = profile["display_name"] as? String
                self.accountEmail = profile["email"] as? String
                return self.sessionPayload()
            }
        }
    }

    @objc func signOut(_ call: CAPPluginCall) {
        Task { @MainActor in
            self.run(call) {
                if self.accessToken != nil {
                    // Best effort: a server that refuses the call must not strand
                    // the app in a session the member has already left.
                    _ = try? await self.send(path: "/api/v1/auth/logout", method: "POST")
                }
                self.clearSession()
                return self.sessionPayload()
            }
        }
    }

    /// Drop every trace of the signed-in member, refresh cookie included. The
    /// cookie lives in the shared store because `URLSession.shared` puts it
    /// there, so clearing the token alone would leave it behind.
    @MainActor private func clearSession() {
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

    // MARK: - Playlist creation and handoff

    @objc func createPlaylist(_ call: CAPPluginCall) {
        let mixId = call.getString("mixId") ?? ""
        let tzOffsetMinutes = call.getInt("tzOffsetMinutes")
        Task { @MainActor in
            self.run(call, timeout: Self.playlistTimeout) {
                // UUID-parsed rather than string-interpolated: the mix id comes
                // from a text field and lands in a URL path.
                guard let mix = UUID(uuidString: mixId.trimmingCharacters(in: .whitespaces)) else {
                    throw ProofError.mixRequired
                }
                guard self.accessToken != nil else { throw ProofError.notSignedIn }
                guard MusicAuthorization.currentStatus == .authorized else {
                    throw ProofError.permissionRequired
                }
                let subscription = try await MusicSubscription.current
                guard subscription.canPlayCatalogContent else {
                    throw ProofError.subscriptionRequired
                }

                let userToken = try await self.musicUserToken()
                var body: [String: Any] = ["music_user_token": userToken]
                if let tzOffsetMinutes { body["tz_offset_minutes"] = tzOffsetMinutes }

                let result = try await self.send(
                    path: "/api/v1/mixes/\(mix.uuidString.lowercased())/apple-playlist",
                    method: "POST",
                    body: body,
                    unauthorized: Self.playlistUnauthorizedCode
                )

                // Report only what the server confirmed. `playlist_url` and
                // `direct_playlist_url` are deliberately dropped: neither
                // resolves on a mobile client, and returning a dead link invites
                // the UI to offer one.
                let unmatched: JSArray = (result["unmatched"] as? [[String: Any]] ?? []).map { track -> JSObject in
                    [
                        "title": track["title"] as? String ?? "",
                        "artist": track["artist"] as? String ?? "",
                        "reason": track["reason"] as? String ?? "no_catalog_match",
                        "source": track["source"] as? String ?? "",
                        "sourceUrl": track["source_url"] as? String ?? ""
                    ]
                }
                return [
                    "playlistName": result["playlist_name"] as? String ?? "",
                    "trackCount": result["track_count"] as? Int ?? 0,
                    "totalCount": result["total_count"] as? Int ?? 0,
                    "unmatched": unmatched
                ]
            }
        }
    }

    /// Answer "does this mix already have a playlist?" from both sides.
    ///
    /// This is the reconciliation step the PRD asks for after an uncertain
    /// result: a timed-out creation is not a failed creation, and retrying blind
    /// is how duplicates happen. Neither side alone is enough. The server knows
    /// whether it recorded a playlist and what it named it; only the device
    /// library knows whether the playlist actually arrived here, which is what
    /// the member will go looking for.
    @objc func reconcile(_ call: CAPPluginCall) {
        let mixId = call.getString("mixId") ?? ""
        Task { @MainActor in
            self.run(call) {
                guard let mix = UUID(uuidString: mixId.trimmingCharacters(in: .whitespaces)) else {
                    throw ProofError.mixRequired
                }
                guard self.accessToken != nil else { throw ProofError.notSignedIn }

                let record = try await self.send(
                    path: "/api/v1/mixes/\(mix.uuidString.lowercased())/apple-playlist",
                    method: "GET"
                )
                // Null playlist_name means no playlist on record for this member.
                let name = record["playlist_name"] as? String ?? ""
                guard !name.isEmpty else {
                    return ["serverHasRecord": false, "playlistName": "", "found": false, "matchCount": 0]
                }

                var result: JSObject = [
                    "serverHasRecord": true,
                    "playlistName": name,
                    "found": false,
                    "matchCount": 0
                ]
                // A library read needs Apple's permission; the server record does
                // not. Report what we could learn rather than failing both halves.
                if MusicAuthorization.currentStatus == .authorized,
                   let found = try await self.libraryPlaylist(named: name) {
                    // A rebuild renames the playlist, so more than one exact-name
                    // match means something else created one too.
                    result["found"] = true
                    result["matchCount"] = found.matches
                    result["trackCount"] = found.tracks
                }
                return result
            }
        }
    }

    /// The named playlist in this device's library, if it is there.
    @MainActor
    private func libraryPlaylist(named name: String) async throws -> (matches: Int, tracks: Int)? {
        var request = MusicLibraryRequest<Playlist>()
        request.filter(matching: \.name, equalTo: name)
        let response = try await request.response()
        guard let playlist = response.items.first else { return nil }
        let detailed = try await playlist.with(.tracks)
        return (matches: response.items.count, tracks: detailed.tracks?.count ?? 0)
    }

    /// Open Apple Music at the member's library.
    ///
    /// Resolves with whether iOS **accepted** the URL. That is not evidence the
    /// member reached the playlist, and nothing here should describe it as such.
    @objc func openMusic(_ call: CAPPluginCall) {
        Task { @MainActor in
            let opened = await UIApplication.shared.open(Self.libraryURL)
            call.resolve(["opened": opened])
        }
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

    @MainActor
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

    /// Map a server status onto something the UI can act on. Callers own the 401
    /// meaning, because it differs by endpoint.
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

    // MARK: - Promise plumbing

    @MainActor private func run(
        _ call: CAPPluginCall,
        timeout timeoutNanoseconds: UInt64 = MMCMusicPlugin.defaultTimeout,
        operation: @escaping @MainActor () async throws -> JSObject
    ) {
        guard !busy else {
            call.reject("An Apple Music operation is still finishing.", "BUSY")
            return
        }
        busy = true
        var settled = false
        let timeout = Task { @MainActor in
            try? await Task.sleep(nanoseconds: timeoutNanoseconds)
            guard !Task.isCancelled && !settled else { return }
            settled = true
            call.reject("Apple Music did not respond in time.", "TIMEOUT")
        }
        Task { @MainActor in
            defer {
                self.busy = false
                timeout.cancel()
            }
            do {
                let result = try await operation()
                guard !settled else { return }
                settled = true
                call.resolve(result)
            } catch {
                guard !settled else { return }
                settled = true
                // Raw SDK errors may carry request details; expose only a category.
                call.reject("Apple Music check failed.", self.errorCode(error))
            }
        }
        // On timeout keep the lock until the SDK operation actually finishes.
        // A late response cannot resolve the promise again or start overlapping work.
        // A reconcile attempted during that window gets BUSY, which is correct:
        // reading the library mid-write would report a half-built playlist.
    }

    private enum ProofError: Error {
        case permissionRequired
        case tokenUnavailable
        case subscriptionRequired
        case notSignedIn
        case credentialsRequired
        case invalidBaseURL
        case mixRequired
        case badResponse
        case network
        case server(String)
    }

    private func errorCode(_ error: Error) -> String {
        if let error = error as? ProofError {
            switch error {
            case .permissionRequired: return "PERMISSION_REQUIRED"
            case .tokenUnavailable: return "TOKEN_UNAVAILABLE"
            case .subscriptionRequired: return "SUBSCRIPTION_REQUIRED"
            case .notSignedIn: return "NOT_SIGNED_IN"
            case .credentialsRequired: return "CREDENTIALS_REQUIRED"
            case .invalidBaseURL: return "SERVER_ADDRESS_INVALID"
            case .mixRequired: return "MIX_ID_INVALID"
            case .badResponse: return "SERVER_ERROR"
            case .network: return "NETWORK_ERROR"
            case .server(let code): return code
            }
        }
        if let error = error as? MusicTokenRequestError {
            switch error {
            case .permissionDenied: return "PERMISSION_REQUIRED"
            case .userNotSignedIn: return "ACCOUNT_REQUIRED"
            case .privacyAcknowledgementRequired: return "PRIVACY_REQUIRED"
            case .userTokenRevoked: return "TOKEN_REVOKED"
            case .developerTokenRequestFailed: return "CONFIGURATION_REQUIRED"
            default: return "SERVICE_ERROR"
            }
        }
        if let error = error as? MusicSubscription.Error {
            switch error {
            case .permissionDenied: return "PERMISSION_REQUIRED"
            case .privacyAcknowledgementRequired: return "PRIVACY_REQUIRED"
            default: return "SERVICE_ERROR"
            }
        }
        return "SERVICE_ERROR"
    }
}
