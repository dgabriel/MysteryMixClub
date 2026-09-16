import AuthenticationServices
import Capacitor

/// Sign in with Apple (MysteryMixClub-4vii.9, Guideline 4.8) via
/// `ASAuthorizationController` -- structurally simpler than
/// `MMCGoogleAuthPlugin`'s `ASWebAuthenticationSession` hand-off, since Apple's
/// own native sign-in sheet runs entirely inside the app with no browser
/// context, no redirect, and so no risk of the app being evicted from memory
/// mid-flow the way Google's web-based login screen was (MysteryMixClub-4vii.21).
///
/// Hands the raw identity token straight back to the caller; the backend
/// (`/auth/apple/native-verify`) verifies its signature against Apple's public
/// keys and resolves the account (app.services.apple_signin) -- this plugin
/// makes no trust decision of its own, same division of responsibility as the
/// Google plugin handing back an opaque one-time code rather than deciding
/// anything about the resulting session itself.
///
/// Requests only the `.email` scope, not `.fullName`: MMC never uses the name
/// Apple would supply (every sign-in method creates an account with an empty
/// `display_name`, see backend's `_create_invited_user`). `.email` IS required
/// even though the backend verifies the identity token's own `email` claim
/// rather than trusting `credential.email` -- Apple only *includes* an email
/// claim in the identity token at all when the request that produced it asked
/// for the `.email` scope; leaving it off doesn't just skip the client-side
/// convenience property, it means the token carries no email whatsoever, on
/// every request, not just the first (MysteryMixClub-4vii.24 -- caught live:
/// every real sign-in failed server-side with "identity token carried no
/// email" until this was added).
private let _requestedScopes: [ASAuthorization.Scope] = [.email]
@objc(MMCAppleAuthPlugin)
public final class MMCAppleAuthPlugin: CAPPlugin, CAPBridgedPlugin, ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    public let identifier = "MMCAppleAuthPlugin"
    public let jsName = "MMCAppleAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "signIn", returnType: CAPPluginReturnPromise)
    ]

    // Held for the request's lifetime so the delegate callback (which carries
    // no reference of its own back to the call that started it) can resolve
    // or reject the right CAPPluginCall.
    private var pendingCall: CAPPluginCall?

    @objc func signIn(_ call: CAPPluginCall) {
        // A second tap while a sheet is already presenting would otherwise
        // silently overwrite pendingCall, leaving the first call's promise
        // never resolved or rejected (MysteryMixClub-4vii.24) -- reject the
        // new call outright rather than let that happen.
        if pendingCall != nil {
            call.reject("A sign-in attempt is already in progress.", "ALREADY_IN_PROGRESS")
            return
        }
        pendingCall = call
        let request = ASAuthorizationAppleIDProvider().createRequest()
        request.requestedScopes = _requestedScopes
        let controller = ASAuthorizationController(authorizationRequests: [request])
        controller.delegate = self
        controller.presentationContextProvider = self
        controller.performRequests()
    }

    public func authorizationController(
        controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let call = pendingCall else { return }
        pendingCall = nil
        guard
            let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
            let tokenData = credential.identityToken,
            let identityToken = String(data: tokenData, encoding: .utf8)
        else {
            call.reject("No identity token received from Apple sign-in.", "NO_TOKEN")
            return
        }
        call.resolve(["outcome": "ok", "identityToken": identityToken])
    }

    public func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        guard let call = pendingCall else { return }
        pendingCall = nil
        // The user dismissed the sheet -- same "no error shown" treatment
        // Google's plugin gives a cancelled ASWebAuthenticationSession.
        if let authError = error as? ASAuthorizationError, authError.code == .canceled {
            call.resolve(["outcome": "cancelled"])
            return
        }
        call.reject("Apple sign-in failed.", "SIGN_IN_FAILED")
    }

    public func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
