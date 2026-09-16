import Capacitor
import StoreKit

/// Voluntary, non-feature-gating tip jar via Apple In-App Purchase
/// (MysteryMixClub-4vii.15). Replaces the web app's Venmo link on iOS --
/// an external payment link is a real App Store Guideline 3.1.1 risk;
/// StoreKit consumables are the App Store-native equivalent. Tips unlock
/// nothing: no club limits, votes, submissions, or status change based on
/// whether or how much a member has tipped.
///
/// Deliberately client-only: these are plain consumables with no
/// server-tracked entitlement to protect (nothing to unlock), so there is
/// no receipt-validation round trip to MMC's backend -- StoreKit's own
/// purchase confirmation is the only source of truth needed here.
@objc(MMCTipsPlugin)
public final class MMCTipsPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MMCTipsPlugin"
    public let jsName = "MMCTips"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getProducts", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "purchase", returnType: CAPPluginReturnPromise)
    ]

    /// Must match the consumable In-App Purchase products created in App
    /// Store Connect under this app's record -- this plugin only reads
    /// prices/metadata StoreKit already has for these ids, it doesn't create
    /// them. Order here is the display order the JS side renders.
    static let productIDs = [
        "com.mysterymixclub.app.tip.small",
        "com.mysterymixclub.app.tip.medium",
        "com.mysterymixclub.app.tip.large"
    ]

    @objc func getProducts(_ call: CAPPluginCall) {
        Task {
            do {
                let products = try await Product.products(for: Self.productIDs)
                // Product.products(for:) does not preserve request order.
                let ordered = Self.productIDs.compactMap { id in products.first { $0.id == id } }
                let payload = ordered.map { product -> [String: Any] in
                    [
                        "id": product.id,
                        "displayName": product.displayName,
                        "displayPrice": product.displayPrice
                    ]
                }
                call.resolve(["products": payload])
            } catch {
                call.reject("Couldn't load tip options.", "PRODUCTS_FAILED")
            }
        }
    }

    @objc func purchase(_ call: CAPPluginCall) {
        guard let productId = call.getString("productId") else {
            call.reject("Missing productId.", "INVALID_ARGS")
            return
        }
        Task {
            do {
                guard let product = try await Product.products(for: [productId]).first else {
                    call.reject("That tip option isn't available.", "PRODUCT_NOT_FOUND")
                    return
                }
                let result = try await product.purchase()
                switch result {
                case .success(let verification):
                    switch verification {
                    case .verified(let transaction):
                        // A consumable, and there's nothing to unlock -- finish
                        // immediately rather than holding it for later delivery.
                        await transaction.finish()
                        call.resolve(["status": "success"])
                    case .unverified:
                        call.reject("Couldn't verify the purchase.", "UNVERIFIED")
                    }
                case .userCancelled:
                    call.resolve(["status": "cancelled"])
                case .pending:
                    call.resolve(["status": "pending"])
                @unknown default:
                    call.reject("Unexpected purchase result.", "UNKNOWN")
                }
            } catch {
                call.reject("The tip couldn't go through.", "PURCHASE_FAILED")
            }
        }
    }
}
