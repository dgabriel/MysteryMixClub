import Capacitor

class ProofViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(MMCMusicPlugin())
        bridge?.registerPluginInstance(MMCTipsPlugin())
        bridge?.registerPluginInstance(MMCGoogleAuthPlugin())
        bridge?.registerPluginInstance(MMCAppleAuthPlugin())
        bridge?.registerPluginInstance(MMCSessionStorePlugin())
        bridge?.registerPluginInstance(MMCAppSettingsPlugin())
    }
}
