import Capacitor
import MusicKit
import UIKit

/// The proof's Capacitor plugin surface: Apple Music authorization, playlist
/// creation, and handoff (ADR 0028, ADR 0029).
///
/// Two credentials exist in this app and **neither crosses the bridge**: Apple's
/// Music User Token, and the MMC access token. Both are held and spent
/// natively; JavaScript receives outcomes only. The MMC session and every HTTP
/// call live in `MMCAPIClient`, not here -- this class owns the Capacitor-
/// facing half (the `@objc` entry points, MusicKit calls, and the busy/timeout
/// promise plumbing), not the server conversation. See ADR 0029 for why the
/// server calls are native at all rather than reusing
/// `frontend/src/services/api.ts`, including the CORS and refresh-cookie
/// consequences that made the reuse path worse than it looks.
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

    @MainActor private let api = MMCAPIClient()

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

    /// A fresh Music User Token, minted against Apple's own automatically-
    /// vended developer token. Only for local connectivity checks (`inspect`)
    /// that never leave the device -- a token minted this way is not what
    /// `musicUserTokenForServer()` below produces, and the two are not
    /// interchangeable at the API (see that function's doc comment).
    @MainActor private func musicUserToken() async throws -> String {
        let provider = MusicDataRequest.tokenProvider
        let developerToken = try await provider.developerToken(options: [])
        let userToken = try await provider.userToken(for: developerToken, options: [])
        guard !userToken.isEmpty else { throw ProofError.tokenUnavailable }
        return userToken
    }

    /// A fresh Music User Token, minted against THIS SERVER's own developer
    /// token rather than Apple's automatically-vended one.
    ///
    /// `MMCAPIClient.createApplePlaylist` spends this token alongside that
    /// same server-signed developer token (ADR 0029: the server owns the
    /// Apple Music HTTP calls). Minting the Music User Token against a
    /// *different* developer token than the one that will actually spend
    /// it -- even a same-team one -- is a real, previously-unverified
    /// mismatch: nothing enforces the two must be interchangeable, and the
    /// web flow never has this problem because MusicKit JS mints its token
    /// against this exact same server-provided developer token already.
    /// `.ignoreCache` forces a fresh mint against this specific developer
    /// token rather than reusing whatever Apple cached for the automatic one.
    @MainActor private func musicUserTokenForServer() async throws -> String {
        let developerToken = try await api.getDeveloperToken()
        let userToken = try await MusicDataRequest.tokenProvider.userToken(
            for: developerToken, options: [.ignoreCache]
        )
        guard !userToken.isEmpty else { throw ProofError.tokenUnavailable }
        return userToken
    }

    // MARK: - MMC session

    @objc func sessionStatus(_ call: CAPPluginCall) {
        Task { @MainActor in
            call.resolve(self.api.sessionPayload())
        }
    }

    @objc func signIn(_ call: CAPPluginCall) {
        let baseURL = call.getString("apiBaseUrl") ?? ""
        let email = call.getString("email") ?? ""
        let password = call.getString("password") ?? ""
        Task { @MainActor in
            self.run(call) {
                try await self.api.signIn(apiBaseUrl: baseURL, email: email, password: password)
            }
        }
    }

    @objc func signOut(_ call: CAPPluginCall) {
        Task { @MainActor in
            self.run(call) {
                await self.api.signOut()
            }
        }
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
                guard self.api.isSignedIn else { throw ProofError.notSignedIn }
                guard MusicAuthorization.currentStatus == .authorized else {
                    throw ProofError.permissionRequired
                }
                let subscription = try await MusicSubscription.current
                guard subscription.canPlayCatalogContent else {
                    throw ProofError.subscriptionRequired
                }

                let userToken = try await self.musicUserTokenForServer()
                let result = try await self.api.createApplePlaylist(
                    mixId: mix, musicUserToken: userToken, tzOffsetMinutes: tzOffsetMinutes
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
                guard self.api.isSignedIn else { throw ProofError.notSignedIn }

                let record = try await self.api.getApplePlaylistRecord(mixId: mix)
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
                call.reject("Apple Music check failed.", errorCode(for: error))
            }
        }
        // On timeout keep the lock until the SDK operation actually finishes.
        // A late response cannot resolve the promise again or start overlapping work.
        // A reconcile attempted during that window gets BUSY, which is correct:
        // reading the library mid-write would report a half-built playlist.
    }
}
