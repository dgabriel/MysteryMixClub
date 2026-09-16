import AuthenticationServices
import Capacitor
import UIKit

/// Native Google Sign-In hand-off via ASWebAuthenticationSession
/// (MysteryMixClub-4vii.21) -- replaces relying on Universal Links to bring
/// the app back after Google's login screen. Two problems with the
/// Universal-Link approach this fixes:
///
/// 1. Google blocks its own OAuth login page inside an embedded WebView
///    (the `disallowed_useragent` policy, enforced since July 2023), so the
///    flow has to leave the app's own WKWebView one way or another.
/// 2. Handing off to full external Safari risks the app being evicted from
///    memory while the user is on Google's login screen (password, 2FA can
///    take a while) -- and Capacitor's `appUrlOpen` event is known not to
///    fire reliably when a Universal Link cold-starts the app afterward
///    (ionic-team/capacitor#6662).
///
/// ASWebAuthenticationSession solves both: Google accepts it as a real
/// browser context, and it's presented as a sheet *on top of* the running
/// app, which stays alive and foregrounded the whole time -- no eviction
/// risk, no cold-start race.
///
/// Its callback is only ever a captured URL, with no cookie jar shared with
/// the app's own WKWebView to rely on -- see the backend's
/// `OAuthExchangeCode` for why the result rides as a one-time code instead
/// of a session cookie.
@objc(MMCGoogleAuthPlugin)
public final class MMCGoogleAuthPlugin: CAPPlugin, CAPBridgedPlugin, ASWebAuthenticationPresentationContextProviding {
    public let identifier = "MMCGoogleAuthPlugin"
    public let jsName = "MMCGoogleAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "signIn", returnType: CAPPluginReturnPromise)
    ]

    /// Passed bare (no "://") per ASWebAuthenticationSession's own
    /// requirement -- this scheme is matched internally by the session
    /// itself and does NOT need a CFBundleURLTypes entry in Info.plist.
    private static let callbackScheme = "mysterymixclub"

    // Held for the session's lifetime so ARC doesn't tear it down mid-flow.
    private var session: ASWebAuthenticationSession?

    @objc func signIn(_ call: CAPPluginCall) {
        guard let apiBaseUrl = call.getString("apiBaseUrl"), !apiBaseUrl.isEmpty else {
            call.reject("Missing apiBaseUrl.", "INVALID_ARGS")
            return
        }
        var components = URLComponents(string: "\(apiBaseUrl)/api/v1/auth/google/login")
        var queryItems = [URLQueryItem(name: "native", value: "true")]
        if let inviteToken = call.getString("inviteToken"), !inviteToken.isEmpty {
            queryItems.append(URLQueryItem(name: "invite_token", value: inviteToken))
        }
        components?.queryItems = queryItems
        guard let url = components?.url else {
            call.reject("Couldn't build the sign-in URL.", "INVALID_ARGS")
            return
        }

        DispatchQueue.main.async {
            let session = ASWebAuthenticationSession(
                url: url,
                callbackURLScheme: Self.callbackScheme
            ) { [weak self] callbackURL, error in
                self?.session = nil

                if let authError = error as? ASWebAuthenticationSessionError,
                   authError.code == .canceledLogin {
                    call.resolve(["outcome": "cancelled"])
                    return
                }
                if error != nil {
                    call.reject("Google sign-in failed.", "SIGN_IN_FAILED")
                    return
                }
                guard
                    let callbackURL = callbackURL,
                    let callbackComponents = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)
                else {
                    call.reject("No callback received from Google sign-in.", "NO_CALLBACK")
                    return
                }
                let items = callbackComponents.queryItems ?? []
                let outcome = items.first { $0.name == "outcome" }?.value ?? "error"
                let code = items.first { $0.name == "code" }?.value ?? ""
                call.resolve(["outcome": outcome, "code": code])
            }
            session.presentationContextProvider = self
            // Shared (non-ephemeral) session: if the user is already signed
            // into Google in Safari, they get the frictionless path rather
            // than re-entering credentials every time. Doesn't affect
            // security here either way -- the exchange-code pattern never
            // trusts ambient cookie state.
            session.prefersEphemeralWebBrowserSession = false
            self.session = session
            session.start()
        }
    }

    public func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
