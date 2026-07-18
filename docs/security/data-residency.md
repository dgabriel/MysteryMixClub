# Hosting Data Residency & International Transfers

Where user data physically lives, and what covers moving it out of the EEA/UK
if any current or future users are there. Filed from the 2026-07-16
compliance gap review (MYS-188).

## Confirmed regions

| Environment | Host | Region | Source |
|---|---|---|---|
| Prod | DO App Platform + managed Postgres | **`nyc`** (New York, USA) | `.do/app.prod.yaml` — `region: nyc` |
| Staging | Self-managed Droplet (`67.207.81.183`) | **Likely `nyc`, not confirmed** | see below |

**Staging is the one that actually matters right now** — it's where real beta
user data lives (see `docs/security/breach-notification-runbook.md`), while
prod is pre-launch with no real users yet.

The Droplet's exact region isn't recorded anywhere in this repo (it was
provisioned by hand, not via a spec file with a `region:` field like the App
Platform apps have). Circumstantial signal: the retired `.do/app.staging.yaml`
spec (no longer used for the actual staging deploy, but written when this
project was first being set up) also declares `region: nyc`, and prod does
too — suggesting `nyc` was the account default at the time and the Droplet
was likely created the same way. **This is an inference, not a confirmed
fact.** `doctl` isn't authenticated in the environment this was written in, so
it couldn't be checked live.

**Action item:** confirm the Droplet's actual region in the DO dashboard
(Droplets → the staging one → region, shown near the top) or via
`doctl compute droplet list`, and update the table above. If it turns out to
be outside the US, re-check the transfer-safeguard reasoning below against
the actual region.

## Does this matter? (the EEA/UK question)

GDPR restricts transferring EU/EEA personal data to a country without an
"adequate" data protection framework (the US isn't one) unless a valid
safeguard is in place. `nyc` (or any US DO region) is outside the EEA/UK, so
this only becomes a live question once MysteryMixClub actually has EU/EEA/UK
users — which, for an invite-only friend-group beta, may currently be zero,
but the product has no geographic restriction, so it's worth having the
answer ready rather than reactive.

## The safeguard: DigitalOcean's DPA + SCCs

Checked directly against DigitalOcean's published legal terms
(`digitalocean.com/legal/data-processing-agreement`, current version as of
2026-07-17):

- DigitalOcean is the data **Processor** for data customers store on their
  services (our database, our Droplet's disk) — MysteryMixClub is the
  Controller. For other activities (account registration, support), both
  parties are Controllers.
- DO's DPA is **automatically incorporated** into the DigitalOcean Customer
  Terms of Service as an addendum — no separate signature or dashboard
  acceptance step is required. This resolves the "has the DPA been accepted?"
  question from MYS-184 for DigitalOcean specifically: it already has been, by
  virtue of having a DO account under their standard terms.
- For international transfers, DO's primary mechanism is the **EU-U.S. Data
  Privacy Framework (DPF)**. If the DPF is ever invalidated (as its
  predecessor, Privacy Shield, was in 2020), the DPA's own terms say the
  **Standard Contractual Clauses (SCCs)** (or the UK Addendum, for UK
  transfers) are incorporated by reference automatically — no re-papering
  needed on our end.

**Bottom line:** hosting in a US DO region is already covered for EU/UK
transfers under DO's standard terms, with no additional action needed from
MysteryMixClub. This should be re-confirmed if DO's DPA changes materially,
or if a different processor is ever added to the stack.

## Privacy Policy cross-reference

The Privacy Policy's subprocessors section (`frontend/src/pages/PrivacyRoute.tsx`,
MYS-184) names DigitalOcean as a subprocessor; it doesn't currently name the
hosting region or transfer mechanism. Given the above is fairly deep legal
detail rather than something a user needs to make a decision, it's being kept
here rather than added to the policy itself — but if EU/EEA users become a
meaningful part of the user base, revisit whether the policy should say more
than "DigitalOcean (hosting our servers and database)".

---

*Last updated 2026-07-17. Re-confirm the staging Droplet's region and update
the table above once checked.*
