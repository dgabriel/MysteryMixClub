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
 *
 * ## Two rules this module exists to enforce (MysteryMixClub-ljl5)
 *
 * **1. Nothing here may hang.** Every promise settles. The original version
 * resolved only on the `musickitloaded` event and rejected only on the script
 * element's `error` event, which left a whole class of failure unhandled: a
 * script request that is intercepted rather than refused — an iOS content
 * blocker answering with an empty 200, Private Relay, a truncated CDN response —
 * fires *neither* event. The promise stayed pending forever, the caller's
 * `finally` never ran, and the UI sat on "building…" with no error and a dead
 * button. Timeouts below are the backstop for exactly that.
 *
 * **2. `authorize()` must run inside the tap.** Apple opens a sign-in window,
 * and mobile Safari grants that only under a live user activation, which does
 * not survive a script download plus an async `configure()`. So loading and
 * configuring are split out into {@link preloadAppleMusic}, called while the
 * reassurance interstitial is on screen; by the time the user commits,
 * {@link authorizeAppleMusic} reaches `authorize()` **synchronously**. Keep it
 * that way — adding an `await` before that call on the warmed path silently
 * reintroduces the mobile bug, and no jsdom test can catch it.
 */

const SDK_URL = "https://js-cdn.music.apple.com/musickit/v3/musickit.js";

/** How long to wait for Apple's SDK before calling it blocked. Generous enough
 *  for a slow phone on mobile data, short enough that a blocked script becomes
 *  an error message rather than an indefinite wait. */
const SDK_TIMEOUT_MS = 15_000;

/** Sign-in is user-paced — Apple ID, possibly two-factor — so this is
 *  deliberately long. It is not a performance budget; it exists only so an
 *  abandoned or blocked window cannot strand the caller forever. */
const AUTHORIZE_TIMEOUT_MS = 180_000;

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

/**
 * Which half of the flow failed, so callers can say something the user can act
 * on. `sdk_blocked` is usually a content blocker and is fixable by the user;
 * `authorize_failed` covers a refused, dismissed, or blocked sign-in window.
 */
export type AppleMusicFailure = "sdk_blocked" | "authorize_failed";

export class AppleMusicError extends Error {
  constructor(
    readonly kind: AppleMusicFailure,
    message: string,
  ) {
    super(message);
    this.name = "AppleMusicError";
  }
}

/** Reject with `onTimeout()` if `promise` has not settled within `ms`. */
function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  onTimeout: () => AppleMusicError,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(onTimeout()), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

let sdkPromise: Promise<MusicKitGlobal> | null = null;

/** Inject the MusicKit script once, resolving when the SDK is ready. */
function loadSdk(): Promise<MusicKitGlobal> {
  if (window.MusicKit) return Promise.resolve(window.MusicKit);
  if (sdkPromise) return sdkPromise;

  const pending = new Promise<MusicKitGlobal>((resolve, reject) => {
    const done = () => {
      if (window.MusicKit) resolve(window.MusicKit);
      else reject(new AppleMusicError("sdk_blocked", "musickit loaded but unavailable"));
    };
    // musickitloaded fires once the global is usable; the load event alone can
    // land before it is.
    document.addEventListener("musickitloaded", done, { once: true });

    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.addEventListener("error", () =>
      reject(new AppleMusicError("sdk_blocked", "could not load musickit")),
    );
    document.head.appendChild(script);
  });

  sdkPromise = withTimeout(
    pending,
    SDK_TIMEOUT_MS,
    () => new AppleMusicError("sdk_blocked", "musickit did not load in time"),
  ).catch((err: unknown) => {
    // Clear the cache on every failure path, timeout included, so a later
    // attempt retries the download rather than replaying the same rejection.
    sdkPromise = null;
    throw err;
  });
  return sdkPromise;
}

/** The configured instance, once warm — the value that lets {@link
 *  authorizeAppleMusic} skip straight to `authorize()` with no `await`. */
let readyInstance: MusicKitInstance | null = null;
let configurePromise: Promise<MusicKitInstance> | null = null;
let configuredToken: string | null = null;

/**
 * Load and configure MusicKit ahead of the click that needs it.
 *
 * Call this when the user is *about* to connect — the reassurance interstitial
 * is the natural window — so the expensive half is done before the tap and
 * `authorize()` can open its window under a live user activation. Safe to call
 * repeatedly: the work is cached per developer token.
 *
 * Rejects with {@link AppleMusicError}. Callers preloading speculatively should
 * swallow that and let the real attempt report it, since there is nothing
 * useful to say to someone who has not asked for anything yet.
 */
export function preloadAppleMusic(developerToken: string): Promise<MusicKitInstance> {
  if (configurePromise && configuredToken === developerToken) return configurePromise;

  configuredToken = developerToken;
  configurePromise = loadSdk()
    .then(async (MusicKit) => {
      await MusicKit.configure({
        developerToken,
        app: { name: "MysteryMixClub", build: "1" },
      });
      const instance = MusicKit.getInstance();
      readyInstance = instance;
      return instance;
    })
    .catch((err: unknown) => {
      configurePromise = null;
      configuredToken = null;
      throw err;
    });
  return configurePromise;
}

/**
 * Run Apple's sign-in and return a Music User Token.
 *
 * Must be called from a user gesture. When {@link preloadAppleMusic} has
 * already warmed the SDK — the expected path — this reaches `authorize()`
 * without awaiting anything first, so the browser still sees the tap that
 * caused it. Cold, it falls back to loading inline, which is correct on
 * desktop and liable to be popup-blocked on mobile; that is the fallback, not
 * the design.
 */
export async function authorizeAppleMusic(developerToken: string): Promise<string> {
  const instance = readyInstance ?? (await preloadAppleMusic(developerToken));
  return withTimeout(
    instance.authorize(),
    AUTHORIZE_TIMEOUT_MS,
    () => new AppleMusicError("authorize_failed", "apple sign-in did not complete"),
  ).catch((err: unknown) => {
    // A refused or dismissed window rejects with Apple's own error; classify it
    // so the caller can offer the sign-in advice rather than a generic retry.
    if (err instanceof AppleMusicError) throw err;
    throw new AppleMusicError("authorize_failed", "apple sign-in failed");
  });
}
