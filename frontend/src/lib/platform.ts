/** True when this bundle was built for the Capacitor iOS shell (ADR 0032),
 *  set only by vite.ios.config.ts. Platform-admin functionality is excluded
 *  from that build entirely -- not just role-gated as web already is -- per
 *  the PRD's "exceptional platform-admin operations remain on web" (IOS-05). */
export const IS_NATIVE_BUILD = import.meta.env.VITE_PLATFORM === "capacitor";
