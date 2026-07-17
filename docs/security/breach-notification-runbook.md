# Data Breach Notification Runbook

What to do if user data is exposed — a leaked credential, a compromised staging
Droplet, an accidentally public backup, etc. Covers GDPR Art. 33 (notifying the
supervisory authority) and Art. 34 (notifying affected individuals). This is a
process document, not legal advice — for a real incident involving EU users,
get an actual privacy lawyer involved alongside these steps, not instead of them.

Filed from the 2026-07-16 compliance gap review (MYS-187). Living document —
update it as the team, infrastructure, or user base grows.

## Where the exposure would actually happen

Two hosts hold user data today (`docs/ci-cd.md` branch model, `docs/staging-setup.md`):

- **Staging** — a self-managed DO Droplet (`67.207.81.183`), Nginx + systemd +
  local Postgres. **This is where real beta users' data actually lives** — it's
  "staging" by deploy pipeline, not by data sensitivity. SSH access, the
  systemd service account, and the local Postgres instance are the realistic
  attack surface.
- **Prod** — DO App Platform + managed Postgres. Smaller attack surface (DO
  manages the OS/patching layer), but currently has no real user data (pre-launch).

A breach practically means one of: the Droplet's SSH key or root access is
compromised, the `mysterymixclub-api` systemd service or its `.env` (secrets,
`DATABASE_URL`) leaks, the Postgres instance is exposed or dumped, or a stolen
JWT/refresh-token cookie compromises one account (a smaller-scope incident that
skips most of the steps below — see "Scope: single account" at the bottom).

## Step 1 — Confirm and contain (as soon as you notice)

1. Rotate anything that could be compromised: `SECRET_KEY` (invalidates every
   JWT — signs everyone out), the Droplet's SSH keys, `RESEND_API_KEY`,
   `DIGITALOCEAN_ACCESS_TOKEN`, Spotify/YouTube credentials, the Postgres
   password.
2. If the Droplet itself is compromised: take it offline (stop
   `mysterymixclub-api` and Nginx, or shut the Droplet down) rather than
   leaving a known-bad host serving traffic while you investigate.
3. Preserve evidence before you clean anything up — copy `/var/log`, the
   systemd journal (`journalctl -u mysterymixclub-api`), and Nginx access logs
   somewhere safe. You'll need these to scope the breach in Step 2.

## Step 2 — Scope it: who's affected and what was exposed

There's no dedicated audit-log table today, so scoping means reasoning from
what the compromised surface had access to:

- **Full DB compromise** (dump, backup leak, root shell on the Droplet) — assume
  every row in `users` (email, display_name), `submissions`/`votes`/`notes`
  (a user's song picks and taste, arguably the most sensitive data in the
  product), and `sessions` (hashed refresh tokens) is exposed. Affected users =
  every non-deleted row in `users`.
- **Single leaked secret** (e.g. `RESEND_API_KEY` alone) — Resend could be used
  to send email *as* MysteryMixClub, but doesn't expose the database. Scope is
  "potential phishing risk to all users," not a data exposure.
- **A single stolen session/JWT** — scope is that one account. Identify via
  the `sessions` row (`user_id`, `device_hint`) if you can tell which token was
  taken; otherwise treat as unknown-single-account and notify that one person
  once identified.

Pull the affected email addresses with a direct query once scope is known:
`SELECT email FROM users WHERE deleted_at IS NULL` (full compromise) or a
narrower `WHERE id = '<user_id>'` for a single-account incident.

## Step 3 — Internal notification

Today "internal" is a team of one (Dawn Gabriel, platform owner) — there's no
separate security/legal/comms function to loop in yet. As the team grows, add
names here. Immediate priority is Step 1 (contain) over internal process.

## Step 4 — The 72-hour authority notification (GDPR Art. 33)

**The clock starts when you become aware of the breach**, not when it happened
or when you've finished investigating — "aware" means having a reasonable
degree of certainty a breach occurred, which is usually Step 1's completion.

- If **any affected user is in the EU/EEA/UK**, GDPR (and UK GDPR) require
  notifying the relevant supervisory authority within 72 hours, **even with an
  incomplete picture** — Art. 33(4) explicitly allows a phased notification
  ("information may be provided in phases without undue further delay").
- MysteryMixClub has no EU establishment and hasn't appointed an EU
  representative (Art. 27) — for a real incident, get a lawyer to confirm
  which authority is actually owed the notification (likely the lead
  supervisory authority where the affected users are concentrated, or —
  absent an EU presence — each affected member state's authority). Don't treat
  the template below as a substitute for that confirmation.
- If **no EU/EEA/UK users are affected**, Art. 33 doesn't apply, but notifying
  affected users directly (Step 5) is still the right thing to do regardless
  of jurisdiction.

**Authority notification — minimum required content (Art. 33(3)):**

1. Nature of the breach (what happened, which systems)
2. Categories and approximate number of affected individuals and records
3. Likely consequences of the breach
4. Measures taken or proposed to address it and mitigate harm
5. A contact point for more information (until a DPO exists, this is the
   platform owner's email)

## Step 5 — Notifying affected users (GDPR Art. 34)

Required when the breach is **likely to result in a high risk** to affected
individuals' rights and freedoms (e.g. their submissions/votes/notes, or
credentials, are exposed) — which a full DB compromise clearly is. Notify
**without undue delay**, in plain language, via the email already on file
(reusing the existing Resend-based email path).

**Template — adjust the bracketed specifics to the actual incident:**

> Subject: Important security notice about your MysteryMixClub account
>
> We're writing to let you know about a security incident that may have
> affected your MysteryMixClub account.
>
> **What happened:** [plain-language description — what was accessed, when,
> how it was discovered].
>
> **What was exposed:** [specific data categories — e.g. "your email address
> and display name" / "the songs and notes you've submitted to your leagues"].
> We do not store payment information, so no payment details were involved.
>
> **What we've done:** [containment steps taken — secrets rotated, systems
> patched/taken offline, etc.].
>
> **What you should do:** [only if relevant — e.g. "as a precaution, you may
> want to sign out of all your devices from your profile page" — the app
> already supports this via "log out of all devices"].
>
> Questions? Reach us at privacy@mysterymixclub.com.

## Scope: single account (lighter path)

For an incident scoped to one account (a stolen session, a phished sign-in
link) — Art. 33/34's population-level thresholds rarely apply to a single
person at "high risk to rights and freedoms" scale, but notifying that one
user directly is still the right move: invalidate their sessions
(`POST /auth/logout-all` already exists for this), and send them the Step 5
template scoped to just their account.

## After the incident

Add a dated entry below (mirroring `docs/security/dependency-audit.md`'s
format) recording what happened, scope, and what changed as a result — this
runbook should get more specific over time, not stay hypothetical forever.

---

*No incidents recorded yet.*
