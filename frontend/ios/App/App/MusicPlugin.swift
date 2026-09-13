import Capacitor
import MusicKit

@objc(MMCMusicPlugin)
public final class MMCMusicPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MMCMusicPlugin"
    public let jsName = "MMCMusic"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "status", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "authorize", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "inspect", returnType: CAPPluginReturnPromise)
    ]

    // All access is confined to the main actor, including promise settlement.
    @MainActor private var busy = false

    private func authorizationName() -> String {
        switch MusicAuthorization.currentStatus {
        case .notDetermined: return "notDetermined"
        case .authorized: return "authorized"
        case .denied: return "denied"
        case .restricted: return "restricted"
        @unknown default: return "unknown"
        }
    }

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
                    let provider = MusicDataRequest.tokenProvider
                    let developerToken = try await provider.developerToken(options: [])
                    let userToken = try await provider.userToken(for: developerToken, options: [])
                    tokenAvailable = !userToken.isEmpty
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

    @MainActor private func run(
        _ call: CAPPluginCall,
        operation: @escaping @MainActor () async throws -> JSObject
    ) {
        guard !busy else {
            call.reject("An Apple Music operation is still finishing.", "BUSY")
            return
        }
        busy = true
        var settled = false
        let timeout = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 30_000_000_000)
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
    }

    private enum ProofError: Error { case permissionRequired }

    private func errorCode(_ error: Error) -> String {
        if error is ProofError { return "PERMISSION_REQUIRED" }
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
