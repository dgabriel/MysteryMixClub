import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        // Must be ProofViewController, not the stock CAPBridgeViewController:
        // it is the one place that registers MMCMusicPlugin
        // (capacitorDidLoad(), ProofViewController.swift). Building the window
        // here in code bypasses the storyboard's own view-controller class, so
        // the plain base class silently never sees our plugin at all --
        // Capacitor.isPluginAvailable('MMCMusic') reads false, and every
        // native-gated control in the UI (including every text field) stays
        // disabled.
        window?.rootViewController = ProofViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}
