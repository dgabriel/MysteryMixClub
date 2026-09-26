import { useEffect, useSyncExternalStore } from "react";
import {
  getConnectivityPhase,
  onBackOnline,
  subscribeConnectivity,
  type ConnectivityPhase,
} from "./connectivity";

/**
 * React side of the offline state (MysteryMixClub-ga4y): the current phase,
 * the "back online" moment, whether reloading would lose a draft, and which
 * component is showing the offline screen.
 */

export function useConnectivityPhase(): ConnectivityPhase {
  return useSyncExternalStore(subscribeConnectivity, getConnectivityPhase, () => "online");
}

/** Calls `callback` when "back online" has shown and data should reload. */
export function useBackOnline(callback: () => void): void {
  useEffect(() => onBackOnline(callback), [callback]);
}

// Fields the member has actually typed into. A field that merely shows a
// saved value (a display name) isn't a draft; one they typed into and that
// still holds text is.
const typedFields = new Set<HTMLInputElement | HTMLTextAreaElement>();
const TYPED_INPUT_TYPES = new Set(["text", "email", "search", "url", "password"]);

if (typeof document !== "undefined") {
  document.addEventListener(
    "input",
    (event) => {
      const target = event.target;
      if (target instanceof HTMLTextAreaElement) typedFields.add(target);
      else if (target instanceof HTMLInputElement && TYPED_INPUT_TYPES.has(target.type)) {
        typedFields.add(target);
      }
    },
    true,
  );
}

/** Whether reloading the page now would throw away something the member typed. */
export function hasUnsavedTyping(): boolean {
  for (const field of typedFields) {
    if (!field.isConnected) typedFields.delete(field);
    else if (field.value.trim() !== "") return true;
  }
  return false;
}

/** Forget typed fields, once the page they belonged to has been reloaded. */
export function forgetTypedFields(): void {
  typedFields.clear();
}

// How many AuthedLayouts are showing the offline state below their nav, so the
// app-level overlay stays out of the way.
let inlineHosts = 0;
const hostListeners = new Set<() => void>();

function subscribeHosts(listener: () => void): () => void {
  hostListeners.add(listener);
  return () => hostListeners.delete(listener);
}

/** Called by AuthedLayout: it renders the offline state in place of its page. */
export function useInlineOfflineHost(): void {
  useEffect(() => {
    inlineHosts += 1;
    hostListeners.forEach((listener) => listener());
    return () => {
      inlineHosts -= 1;
      hostListeners.forEach((listener) => listener());
    };
  }, []);
}

export function useHasInlineOfflineHost(): boolean {
  return useSyncExternalStore(
    subscribeHosts,
    () => inlineHosts > 0,
    () => false,
  );
}
