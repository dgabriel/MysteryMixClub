import Capacitor
import UIKit

/// Opens this app's notification settings in iOS Settings
/// (MysteryMixClub-gxh3). After someone denies push, iOS never shows the
/// system prompt again, so the only way back is Settings; Capacitor's core has
/// no API for opening it. iOS 16+ (the deployment target) can link straight to
/// the app's notification settings rather than its top-level page.
@objc(MMCAppSettingsPlugin)
public final class MMCAppSettingsPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MMCAppSettingsPlugin"
    public let jsName = "MMCAppSettings"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "openNotificationSettings", returnType: CAPPluginReturnPromise)
    ]

    @objc func openNotificationSettings(_ call: CAPPluginCall) {
        guard let url = URL(string: UIApplication.openNotificationSettingsURLString) else {
            call.reject("Couldn't open settings.", "SETTINGS_UNAVAILABLE")
            return
        }
        DispatchQueue.main.async {
            UIApplication.shared.open(url) { opened in
                if opened {
                    call.resolve()
                } else {
                    call.reject("Couldn't open settings.", "SETTINGS_UNAVAILABLE")
                }
            }
        }
    }
}
