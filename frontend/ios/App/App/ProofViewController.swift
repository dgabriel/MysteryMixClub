import Capacitor

class ProofViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(MMCMusicPlugin())
        bridge?.registerPluginInstance(MMCTipsPlugin())
    }
}
