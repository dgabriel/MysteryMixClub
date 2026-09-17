import { initializePushListeners, nativePushAvailable } from "../ios/push";

type MinimalRouter = { navigate: (to: string) => void };

/**
 * Routes a tapped push notification into the already-running app
 * (MysteryMixClub-4vii.27, IOS-04), mirroring `deepLinks.ts`'s own
 * `router.navigate` shape for Universal Links.
 *
 * Lands on the club's home screen (`/clubs/:id`), the same destination
 * `notifications.py`'s own email CTA link uses for every one of these
 * events (`_club_url`) -- not the specific mix's own detail page, so a tap
 * always lands somewhere sensible even if the mix has since advanced past
 * the state the notification described (PRD IOS-04: "a late notification
 * opens current state gracefully").
 */
export function registerPushDeepLinkHandler(router: MinimalRouter): void {
  if (!nativePushAvailable()) return;

  initializePushListeners((data) => {
    if (data.club_id) {
      router.navigate(`/clubs/${data.club_id}`);
    }
  });
}
