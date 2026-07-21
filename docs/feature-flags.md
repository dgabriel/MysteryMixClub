# Feature Flags

App-level toggles flipped **per environment via env vars** — no code change, no
redeploy. This is the registry of every flag plus the convention for adding new
ones. As new ideas land, add a flag here.

> Flags are plain settings on `backend/app/config.py` (`Settings`), read through
> `get_settings()`. We deliberately keep them as simple env-driven booleans
> rather than a flag service — there's no per-user/percentage targeting today.
> If we ever need that, this doc is where we'll record the shift. Rationale:
> `docs/adr/0001-feature-flags-as-env-booleans.md`.

---

## How to add a flag

1. **Define it** in `app/config.py` under the **Feature flags** banner. Name the
   boolean clearly, **default it `False`** (off is safe in production), and keep
   any companion config (e.g. a target address) beside it.
2. **Read it** via `get_settings()` where the behavior branches. Prefer wiring
   the decision in one place (a builder/factory) over scattering `if settings.x`
   across call sites.
3. **Document it** in the registry below.
4. **Add it to `.env.example`** (key + safe default, no secret values) so the
   contract is discoverable.
5. **If it's used in a deployed env**, set it in the relevant place:
   - **Staging** (Droplet): `scripts/staging.env` (see `docs/staging-setup.md`).
   - **Prod** (App Platform): the `.do/app.prod.yaml` env block / DO dashboard.
6. **Test both states** — a flag with an untested branch is a latent bug.

### Conventions

- **Default off.** Production runs the safe path unless explicitly turned on.
- **Fail safe.** If a flag is on but its companion config is missing, choose the
  non-destructive behavior (e.g. suppress rather than send to real users).
- **Boolean name says what turning it on does** (`email_redirect_to_test`, not
  `email_mode`). Companion config is a separate setting (`email_test_recipient`).
- **Document here on the same PR** that introduces the flag.

---

## Registry

### `EMAIL_REDIRECT_TO_TEST` — staging email sink

| | |
|---|---|
| **Env var** | `EMAIL_REDIRECT_TO_TEST` (bool) |
| **Companion** | `EMAIL_TEST_RECIPIENT` (email address) |
| **Default** | `false` |
| **Code** | `app/config.py`, applied in `app/services/email.py` `build_email_sender` (wraps the sender in `RedirectingEmailSender`) |
| **Introduced** | MYS-109 (email notifications) |
| **Use in** | staging (testing). **Leave off in production.** |

**What it does.** When `true`, **every outbound email** — mystery-mix-lifecycle
notifications *and* magic links — is redirected to `EMAIL_TEST_RECIPIENT` instead
of the real recipient. The intended recipient is preserved in the subject as
`[→ real@addr] <subject>` so the test inbox shows who each message was for.

**Fail-safe.** If `EMAIL_REDIRECT_TO_TEST=true` but `EMAIL_TEST_RECIPIENT` is
empty, email is **suppressed** (logged, not sent) rather than risk reaching real
recipients. With the flag `false`, delivery is normal.

**Interaction with sending.** Real delivery still requires `RESEND_API_KEY`;
without it the app logs emails (`ConsoleEmailSender`) regardless of this flag.

**How to test on staging.**
1. Set in the staging env: `RESEND_API_KEY=…`, `EMAIL_TEST_RECIPIENT=you+mmc-test@gmail.com`,
   `EMAIL_REDIRECT_TO_TEST=true`, `API_BASE_URL=https://<staging-api-host>`.
2. Restart the API service to pick up the env.
3. Drive a mystery mix: open submission → open voting → close. Each transition emails;
   all land in the test inbox, subject-tagged with the real recipient.
4. Verify deliverability via Gmail "Show original" (SPF/DKIM/DMARC pass) and the
   native Unsubscribe button (from the `List-Unsubscribe` header). See MYS-123.
5. Flip to real delivery: set `EMAIL_REDIRECT_TO_TEST=false`, restart.

### `WAITLIST_ENABLED` — public pre-launch waitlist

| | |
|---|---|
| **Env var** | `WAITLIST_ENABLED` (bool) |
| **Companion** | none |
| **Default** | `false` |
| **Code** | `app/config.py`; checked in `app/api/routes/waitlist.py` (`GET /waitlist/enabled`, `POST /waitlist`) |
| **Introduced** | MYS-215 (temporary — replaces "email us for an invite" while the app is pre-launch) |
| **Use in** | wherever the waitlist should be live. Off reverts the login page to the "email us" copy with no code change. |

**What it does.** When `true`, the login page shows a small "join the
waitlist" form instead of the mailto "email us" copy, and `POST /waitlist`
accepts join requests (format-validated, duplicate-rejected). When `false`,
`POST /waitlist` 404s and the frontend's `GET /waitlist/enabled` check tells
it to render the old copy instead. Admin invites waitlist entries manually
from `/admin` (`POST /admin/waitlist/{id}/invite`) — that admin flow works
regardless of this flag (an admin can always invite anyone who's already on
the waitlist from a time the flag was on).

**Fail-safe.** No companion config to misconfigure. If the frontend's
`GET /waitlist/enabled` check itself fails (network error), `EmailEntryScreen`
falls back to the "email us" copy rather than showing a broken form.

**How to test.** Set `WAITLIST_ENABLED=true`, restart. Visit the login page —
the waitlist form should replace the "email us" line. Submit an email, then
check `/admin` → waitlist section shows the entry; click "invite" and confirm
the email sends (or logs, in dev/without `RESEND_API_KEY`) with a working
`/invite/:token` link. Set back to `false` and restart to confirm the login
page reverts to the "email us" copy and `POST /waitlist` 404s.

---

## Template for a new flag

```
### `FLAG_NAME` — one-line purpose

| | |
|---|---|
| **Env var** | `FLAG_NAME` (bool) |
| **Companion** | `…` (or "none") |
| **Default** | `false` |
| **Code** | where it's defined / where it branches |
| **Introduced** | MYS-### |
| **Use in** | which environment(s) |

What it does. … Fail-safe. … How to test. …
```
