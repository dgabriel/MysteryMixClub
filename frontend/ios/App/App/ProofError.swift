import MusicKit

/// The vocabulary of everything that can go wrong across the iOS proof, and
/// how it gets spelled as a bridge `code` string --
/// `frontend/src/ios/music.ts`'s `musicErrorMessage()` switches on exactly
/// these values.
enum ProofError: Error {
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

/// Map any error this proof can throw -- a `ProofError`, or a raw MusicKit
/// error -- onto its bridge code.
///
/// Split by error family rather than one long function: each family's own
/// switch is a natural, independent unit on its own vocabulary, and this is
/// also what keeps any one of them within SwiftLint's cyclomatic-complexity
/// budget -- a single function doing all three was measured at complexity 22
/// against a limit of 10.
func errorCode(for error: Error) -> String {
    if let error = error as? ProofError { return proofErrorCode(error) }
    if let error = error as? MusicTokenRequestError { return musicTokenErrorCode(error) }
    if let error = error as? MusicSubscription.Error { return musicSubscriptionErrorCode(error) }
    return "SERVICE_ERROR"
}

private func proofErrorCode(_ error: ProofError) -> String {
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

private func musicTokenErrorCode(_ error: MusicTokenRequestError) -> String {
    switch error {
    case .permissionDenied: return "PERMISSION_REQUIRED"
    case .userNotSignedIn: return "ACCOUNT_REQUIRED"
    case .privacyAcknowledgementRequired: return "PRIVACY_REQUIRED"
    case .userTokenRevoked: return "TOKEN_REVOKED"
    case .developerTokenRequestFailed: return "CONFIGURATION_REQUIRED"
    default: return "SERVICE_ERROR"
    }
}

private func musicSubscriptionErrorCode(_ error: MusicSubscription.Error) -> String {
    switch error {
    case .permissionDenied: return "PERMISSION_REQUIRED"
    case .privacyAcknowledgementRequired: return "PRIVACY_REQUIRED"
    default: return "SERVICE_ERROR"
    }
}
