import { useSyncExternalStore } from "react";
import {
  getPushRegistrationState,
  subscribePushRegistration,
  type PushRegistrationState,
} from "../ios/push";

/** Whether the backend has this device's push token for the signed-in account
 *  (MysteryMixClub-4vii.32) -- distinct from OS permission. */
export function usePushRegistration(): PushRegistrationState {
  return useSyncExternalStore(
    subscribePushRegistration,
    getPushRegistrationState,
    getPushRegistrationState,
  );
}
