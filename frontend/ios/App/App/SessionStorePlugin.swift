import Capacitor
import Security

/// Holds the session's refresh token in the Keychain (MysteryMixClub-kw2u,
/// ADR 0037). The web app keeps it in an HttpOnly cookie, but this WebView's
/// origin (capacitor://localhost) is cross-site to the API, so the
/// SameSite=Lax cookie is never sent back: refresh and logout both failed on
/// iOS. The backend returns the token in the sign-in body only for this origin,
/// and the JS side sends it back in an `X-Refresh-Token` header.
///
/// One item, this device only: `AfterFirstUnlockThisDeviceOnly` keeps it out of
/// iCloud Keychain and device backups, while still readable when the app
/// launches in the background after the phone's first unlock.
@objc(MMCSessionStorePlugin)
public final class MMCSessionStorePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MMCSessionStorePlugin"
    public let jsName = "MMCSessionStore"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getRefreshToken", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setRefreshToken", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearRefreshToken", returnType: CAPPluginReturnPromise)
    ]

    private static let baseQuery: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.mysterymixclub.app.session",
        kSecAttrAccount as String: "refresh_token"
    ]

    @objc func getRefreshToken(_ call: CAPPluginCall) {
        var query = Self.baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound {
            call.resolve(["token": NSNull()])
            return
        }
        guard status == errSecSuccess, let data = item as? Data,
              let token = String(data: data, encoding: .utf8) else {
            call.reject("Couldn't read the saved session.", "KEYCHAIN_READ_FAILED")
            return
        }
        call.resolve(["token": token])
    }

    @objc func setRefreshToken(_ call: CAPPluginCall) {
        guard let token = call.getString("token"), !token.isEmpty,
              let data = token.data(using: .utf8) else {
            call.reject("Missing token.", "INVALID_ARGS")
            return
        }
        // Replace rather than update: one item, whatever a previous sign-in left.
        SecItemDelete(Self.baseQuery as CFDictionary)
        var item = Self.baseQuery
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else {
            call.reject("Couldn't save the session.", "KEYCHAIN_WRITE_FAILED")
            return
        }
        call.resolve()
    }

    @objc func clearRefreshToken(_ call: CAPPluginCall) {
        let status = SecItemDelete(Self.baseQuery as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            call.reject("Couldn't clear the saved session.", "KEYCHAIN_DELETE_FAILED")
            return
        }
        call.resolve()
    }
}
