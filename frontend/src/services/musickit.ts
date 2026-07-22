/**
 * MusicKit JS loader + authorize helper (MYS-108).
 *
 * Isolated from the component so the Apple UI can be tested without Apple's SDK:
 * tests stub `authorizeAppleMusic`, and nothing here runs unless a user actually
 * clicks connect. The script is only injected on demand — a member who never
 * touches Apple never pays for the download.
 *
 * The developer token is safe in the browser: it identifies the app, not a user
 * (Apple's own web embeds ship it client-side). The `.p8` that signs it stays
 * on the server.
 */

const SDK_URL = "https://js-cdn.music.apple.com/musickit/v3/musickit.js";

type MusicKitInstance = { authorize: () => Promise<string> };
type MusicKitGlobal = {
  configure: (options: {
    developerToken: string;
    app: { name: string; build: string };
  }) => Promise<unknown>;
  getInstance: () => MusicKitInstance;
};

declare global {
  interface Window {
    MusicKit?: MusicKitGlobal;
  }
}

let sdkPromise: Promise<MusicKitGlobal> | null = null;

/** Inject the MusicKit script once, resolving when the SDK is ready. */
function loadSdk(): Promise<MusicKitGlobal> {
  if (window.MusicKit) return Promise.resolve(window.MusicKit);
  if (sdkPromise) return sdkPromise;

  sdkPromise = new Promise<MusicKitGlobal>((resolve, reject) => {
    const done = () => {
      if (window.MusicKit) resolve(window.MusicKit);
      else reject(new Error("musickit loaded but unavailable"));
    };
    // musickitloaded fires once the global is usable; the load event alone can
    // land before it is.
    document.addEventListener("musickitloaded", done, { once: true });

    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.addEventListener("error", () => {
      sdkPromise = null; // let a later attempt retry rather than fail forever
      reject(new Error("could not load musickit"));
    });
    document.head.appendChild(script);
  });
  return sdkPromise;
}

/**
 * Run Apple's sign-in popup and return a Music User Token.
 *
 * Must be called from a user gesture — Apple opens a popup, and browsers block
 * popups that aren't tied to a click.
 */
export async function authorizeAppleMusic(developerToken: string): Promise<string> {
  const MusicKit = await loadSdk();
  await MusicKit.configure({
    developerToken,
    app: { name: "MysteryMixClub", build: "1" },
  });
  return MusicKit.getInstance().authorize();
}
