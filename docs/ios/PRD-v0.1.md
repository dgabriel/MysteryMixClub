# Mystery Mix Club for iOS

Product requirements document · Draft v0.1 · September 12, 2026

Owner: To be confirmed  
Release: First iPhone release  
Status: First pass for discussion; proposed scope and targets are not yet approved.

## 1. Product intent

Bring the existing Mystery Mix Club experience to iPhone with dependable reminders and a substantially smoother Apple Music connection. Members should spend their time sharing and discovering music with friends, without troubleshooting sign-in windows or finding their way back to a mix.

This release extends the existing product and backend. It preserves clubs, accounts, submissions, participation modes, voting, notes, and results across web and iOS.

### Problems to solve

1. Members need timely reminders to submit, vote, and see reveals without relying on email or remembering to open the website.
2. Some Apple Music users encounter blocked authorization popups and awkward or unsuccessful returns to MMC.
3. Leaving MMC to listen should not lose the current mix, sign-in session, or unfinished work.

### Primary outcome

A member opens a reminder, reaches the correct mix, connects Apple Music through native iOS authorization when needed, creates or opens the mix playlist, and resumes participation in MMC without repeating completed steps.

## 2. Users and principles

**Members:** Existing and invited users who submit songs, listen, leave notes, vote when Playing, and enjoy the reveal.

**Organizers and co-organizers:** Members who create clubs, invite friends, configure themes and deadlines, and manage the mix lifecycle.

Preserve these existing product principles:

- Streaming-service choice must not determine eligibility to participate. Apple Music connection is optional.
- Just Vibing remains private: the member's song competes equally, but the member does not vote and sees the existing limited results view.
- Most Noted remains a parallel recognition of resonance.
- No additional account or separate club data is created merely because someone installs iOS.
- Collect only the operational data needed to deliver and improve this experience. Do not collect music credentials or use listening preferences for advertising.

## 3. Release scope

| Included in first release | Deferred or excluded |
|---|---|
| Existing member loop: join, submit, listen, vote, notes, reveal | Playback inside MMC, background audio, lock-screen playback controls |
| Native Apple Music authorization and playlist handoff | Android implementation; scope separately after iOS validation |
| Push lifecycle updates and actionable deadline reminders | Widgets, Live Activities, Apple Watch, dedicated iPad layouts |
| Reliable invitation, authentication, and notification links | Receiving songs through an iOS share extension |
| Existing Spotify playlist access and external listening links | New personal Spotify account connection or playback-control integration |
| Profile, preferences, logout, account deletion | Payments, tips, ads, subscriptions |
| Basic club creation and organizer operations | Platform administration and analytics screens; continue on web |
| Offline/error states and local draft preservation | Offline submission/voting queues and offline music |
| Release-required user-content safeguards | Broad redesign or new game mechanics |

Spotify scope is intentionally a proposal: the current backend creates shared-account playlists. Native per-member Spotify authorization is a separate feature, not implied by existing playlist support.

## 4. Key journeys

### A. Join and participate

Open an invitation → reach the correct club context → authenticate or register through an eligible existing flow → complete onboarding → join the club → see its current mix.

Installed-app links open MMC where configured. Without the app, the invitation remains usable on the web. Automatic restoration after a subsequent App Store installation is not assumed; the user may reopen the original invitation.

### B. Connect Apple Music and listen

Open a mix → choose Apple Music → see a concise explanation of access → request native iOS authorization → continue the requested playlist action → show its actual result → offer to open Apple Music.

Previously authorized users bypass the explanatory connection step when access remains valid. Account setup, subscription eligibility, device restrictions, or revoked permission may still require action; the app explains the applicable condition without presenting a generic endless spinner.

### C. Respond to a reminder

Receive a relevant reminder → tap it → authenticate if necessary → return to the intended mix → see its current state and available action.

A notification is a route into current server state, not authority to submit or vote after a deadline.

### D. Resume after listening

Leave MMC for a music app → return through the app switcher or a supported return mechanism → see the same mix → restore the draft where applicable → refresh server state before accepting changes.

MMC must not promise to force an automatic return from a third-party music app. Successful return means preserving context whenever the user returns.

## 5. Functional requirements

### IOS-01 — Identity, onboarding, and links

- Reuse existing MMC accounts, invitation rules, onboarding, and backend authorization.
- Support email magic-link and password flows in iOS, including reset links and session expiry recovery.
- Preserve the intended destination through authentication; reject invalid or unauthorized destinations safely.
- Implement an explicit, secure native session strategy rather than assuming browser cookies transfer between Safari and the app.
- Logout and account deletion clear local account data, drafts, and push associations. Logout-all continues to invalidate other sessions.
- If Google sign-in ships in iOS, provide a compliant equivalent login option; Sign in with Apple is the proposed approach, subject to implementation scoping. Apple Music authorization is separate from MMC account sign-in.

**Acceptance:** A new invited user and a returning member can reach the intended club or mix from cold-start and already-open app states. An expired link offers a recoverable path. No access token is placed in a navigation URL.

### IOS-02 — Native Apple Music connection

- Use native iOS MusicKit authorization for the iOS connection flow instead of MusicKit JS popup authorization.
- Model connection status explicitly: not requested, authorized, denied/restricted, and actionable account/subscription or service errors.
- Recheck authorization as needed on resume and before protected operations; do not equate a cached UI flag with valid access.
- Continue the initiating playlist action after successful authorization without requiring the user to find and repeat the action.
- Cancellation, denial, and timeout leave the mix usable and never indicate a successful connection.
- Handle permission changes, account changes, unavailable network, and ineligible subscriptions with specific recovery guidance where the platform exposes enough information.

**Acceptance:** An eligible signed-in Apple Music subscriber can connect on a physical iPhone without a browser authorization popup. Subsequent authorized use does not unnecessarily repeat consent. All failure paths settle into usable UI.

### IOS-03 — Playlist creation and music handoff

- Preserve the current per-member Apple Music library playlist model and backend song-resolution behavior.
- Verify how native MusicKit authorization supports the existing server playlist API; adapting that boundary is part of the prototype.
- Show creation progress, successful track counts, missing tracks, and recoverable failure accurately.
- Prevent duplicate creation caused by repeated taps or a retry after an uncertain result; reconcile existing work before retrying where supported.
- Offer to open the created playlist when a verified usable target is available. Provide clear library-location guidance when direct opening is not reliably supported.
- Retain Spotify shared-playlist access and available links to other supported services. Do not silently replace an unavailable track with an uncertain match.
- Preserve the current mix and session during external handoff. Do not treat opening a link as proof the user listened.

**Acceptance:** Test successful creation, partial track availability, authorization failure, network interruption, repeated taps, and return from Apple Music. The UI never claims more tracks were created than the service confirmed.

### IOS-04 — Push notifications

| Event | Recipient and proposed behavior |
|---|---|
| Submission opens | Eligible current members; open that mix |
| Submission deadline approaches | Members still needing to submit |
| Voting opens | Eligible members; open the listening/voting screen |
| Voting deadline approaches | Playing members with an outstanding voting action under existing rules |
| Mix closes / reveal available | Current members; open the appropriate results view |

- Ask for notification permission in context after the user understands the club experience; denial does not block participation.
- Provide separate lifecycle-update and deadline-reminder preferences. Retain independent email preferences; enabling push does not silently disable email.
- Proposed initial reminder cadence: one reminder 24 hours before each deadline, only when that time is still in the future and the action remains outstanding. Confirm cadence before implementation.
- Re-evaluate eligibility against current membership, participation, completed actions, and deadline changes before dispatch.
- Deduplicate events and reminders across retries. Retire invalid device registrations and remove account associations on logout or deletion.
- Avoid sending stale reminders after a mix advances. A late notification opens current state gracefully.
- Use restrained lock-screen copy; do not reveal anonymous submitters, private participation mode, or hidden results.
- Do not rely on guaranteed or immediate delivery. In-app state and existing email remain available when push is disabled or delayed.

**Acceptance:** Permission granted/denied, token changes, logout/account switching, completed actions, changed deadlines, removed membership, and notification taps from terminated/background/foreground app states are covered in QA.

### IOS-05 — Complete club experience

- Preserve search and paste-link submission, confirmation, editing where allowed, participation selection, voting budgets and self-vote prevention, notes, reveals, and history.
- Preserve server-side anonymity and access controls; the native client does not receive hidden data merely to hide it visually.
- Preserve Playing and Just Vibing results differences and Most Noted behavior.
- Include club creation, invitations, theme/deadline editing, and allowed lifecycle controls for authorized organizers. Exceptional platform-admin operations remain on web.
- Web and iOS changes appear consistently after refresh; the backend remains authoritative.

**Acceptance:** At least one club completes submission → voting → reveal using mixed web and iOS participants, including Playing and Just Vibing members and an organizer.

### IOS-06 — Mobile resilience and accessibility

- Preserve unsent submission and vote drafts across ordinary backgrounding and app restart, scoped to the signed-in account. Revalidate on restoration and submission; explain when the mix state makes a draft obsolete.
- Never label an unsent draft as submitted. Failed mutations offer safe retry/reconciliation behavior.
- Refresh relevant data on resume without unexpectedly wiping unfinished work.
- Provide useful loading, offline, empty, and retry states. No indefinite spinner.
- Respect safe areas, keyboard visibility, text scaling, VoiceOver, contrast, and reduced motion. Keep the established MMC visual identity.

**Acceptance:** Core journeys work on the smallest supported iPhone layout and a larger device, with enlarged text and VoiceOver. Background/foreground transitions and interrupted network requests do not cause silent loss or duplicate writes.

## 6. Proposed implementation direction

Use Capacitor to retain the existing React interface and FastAPI backend, with a native Swift MusicKit bridge and native push support. This is a candidate architecture, not an approved ADR.

The first technical milestone must establish native authorization, playlist creation, opening Apple Music, and restoring MMC context on a physical device. It must also establish secure handling of the native authorization/session boundary. Choose or build a bridge only after checking its capabilities and maintenance suitability.

React Native remains an alternative if the prototype exposes significant integration or experience limitations. Rewriting the UI is not itself a solution to authorization problems.

Maintain the web MusicKit flow separately for PWA users. Keep backend changes compatible with the deployed web client and supported older app versions. Record the final architecture in the repository's ADR process before implementation depends on it.

## 7. Release readiness and privacy

- Configure Apple developer capabilities, signing, production endpoints, notification credentials, and supported links.
- Supply reviewer access to an invite-only account/club with an understandable test journey.
- Complete accurate privacy disclosures and permission-purpose copy; keep account deletion discoverable.
- Assess and implement user-content filtering, reporting, blocking, support contact, and response handling appropriate to notes and other member content. Exact moderation behavior requires a defined owner and scope before store submission.
- Confirm the iOS login lineup against Apple's current login-services requirements.
- Exclude secrets, authorization tokens, song notes, and raw invitation links from telemetry and logs. Use aggregate operational measurements with a defined retention period.
- Confirm minimum supported iOS version and device matrix during the prototype. iPhone is the first-release design target.

## 8. Success measures and release gates

Proposed targets, to be calibrated during beta:

| Measure | Initial target / gate |
|---|---|
| Eligible Apple Music connection attempts | At least 95% succeed in beta; report numerator, denominator, cancellations, and failure categories separately |
| Browser authorization popups in the native Apple Music path | Zero |
| Repeated consent with valid authorization | Zero in the scripted regression matrix |
| Lost mix/session context on ordinary music-app return | Zero reproducible cases in release QA |
| Deadline push eligibility | No known reminders sent after action completion or loss of membership in the controlled test matrix |
| Core club loop | Complete mixed web/iOS beta cycle without a blocking issue |
| Data integrity and privacy | No unresolved critical/high-severity defects involving lost writes, duplicate writes, anonymity, or account isolation |

Track push dispatch acceptance separately from notification opens; neither establishes device delivery. Measure Apple Music failures by authorization, playlist creation, and handoff stage rather than one blended error rate.

Record current web friction qualitatively and, where feasible, with comparable aggregate measurements. Low beta sample sizes must be disclosed rather than presented as evidence of population-wide reliability.

## 9. Milestones and estimation

1. **Integration proof:** Native authorization → playlist creation → music-app handoff → resume. Validate denied permission, cancellation, missing eligibility, and interrupted network. Initial planning allowance: 3–5 focused working days; unresolved integration issues can extend it.
2. **Usable iOS alpha:** Secure MMC sessions, links, existing member screens, draft preservation, and initial notification delivery.
3. **Club beta through TestFlight:** Complete a real club cycle, gather Apple Music failure evidence, tune reminders, and fix device-specific issues.
4. **Store candidate:** Accessibility, content safeguards, privacy disclosures, reviewer setup, regression testing, and release operations.

Re-estimate milestones 2–4 after the integration proof using the owner's demonstrated agent-driven development pace. The existing PWA took approximately 3–4 weeks with specified features; that informs capacity but does not establish mobile SDK or store-review duration. No public launch date is committed by this draft.

## 10. Decisions to resolve

| Decision | Proposed default |
|---|---|
| iOS interface architecture | Capacitor plus native MusicKit, contingent on prototype |
| Spotify v1 depth | Preserve shared-playlist access and reliable external links; defer personal connection |
| Google login in iOS | Include only alongside a compliant equivalent option; scope Sign in with Apple explicitly |
| Deadline cadence | One actionable reminder 24 hours before each deadline; confirm quiet-hours expectations |
| Organizer scope | Existing routine club management in-app; platform administration on web |
| Direct Apple playlist opening | Validate on device; provide honest library guidance if unavailable |
| Supported devices and OS | iPhone first; minimum iOS version set after SDK validation |
| Moderation operations | Define reporting/blocking semantics and response owner before release |

## 11. Basis and references

This draft draws on the current local develop checkout, its existing PRD and technical design, and the owner's stated priorities. Reviewed implementation areas include the React route map, API/session client, MusicKit JS authorization, mix interface, email notification service, and PWA shell. It is not a live integration audit. Older PRD references to Odesli, league/round terminology, and monetization are not adopted as new iOS requirements; preserve current implemented provider and product behavior.

- [Apple MusicKit](https://developer.apple.com/musickit/)
- [Native MusicKit authorization](https://developer.apple.com/documentation/musickit/musicauthorization/request%28%29)
- [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/) — particularly user content and login services
- [Capacitor documentation](https://capacitorjs.com/docs)
