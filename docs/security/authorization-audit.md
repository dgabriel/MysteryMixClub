# Authorization Audit — Per-Club Data Isolation

Technical-design §9: *"Row-level security on PostgreSQL — players can only access
their own club data."* This records the pre-launch audit (MYS-48) of every
authenticated endpoint and the enforcement-mechanism decision.

> **Note on identifier names (MYS-195/MYS-196).** The club/mystery-mix rename
> kept the API route layer's internal Python parameter and helper-function
> names on the old league/round vocabulary as a deliberate, permanent split
> from the club/mix wire vocabulary (see `backend/app/api/wire.py`). The two
> guard helpers below are `_load_club_as_member(league_id, ...)` and
> `_load_club_as_organizer(league_id, ...)` in `app/api/routes/clubs.py` — the
> function names were updated to club/mix, but their `league_id`/`round_id`
> parameters were not. This doc uses club/mystery-mix vocabulary in prose and a
> generic `:id` placeholder in route paths; where it names an actual Python
> identifier, that identifier is quoted verbatim.

## Decision: app-layer enforcement (not DB RLS) for v1

Per-club isolation is enforced **at the application layer**, primarily via two
shared helpers in `app/api/routes/clubs.py` (the invite-creation route inlines
an equivalent active-member check rather than calling the helper):

- `_load_club_as_member(league_id, user, db)` → 404 if the club is missing,
  403 if the caller has no active (`removed_at IS NULL`) `club_members` row.
- `_load_club_as_organizer(league_id, user, db)` → 404 if missing, 403 unless
  the caller is the club's `organizer_id`.

**Why app-layer, not Postgres RLS, for v1:**

- Every club-scoped route already derives the club **from the resource**
  (mystery mix → `club_id`, submission → mystery mix → `club_id`, note →
  submission → mystery mix → `club_id`) and then calls a guard. There is no
  path that trusts a client-supplied club id to authorize a differently-owned
  resource, so there is no confused-deputy surface for RLS to backstop.
- The app uses a single DB role; RLS would require per-request `SET ROLE` /
  session GUCs and policy upkeep on every table — material complexity for a
  single-binary FastAPI app at friend-group scale.
- The guard pattern is uniform, centralized in two helpers, and covered by
  negative tests on every endpoint (see below), so enforcement is auditable in
  one place.

**Revisit RLS if:** the app moves to multi-tenant DB roles, adds raw-SQL report
endpoints that bypass the helpers, or exposes a direct query surface. Until then,
app-layer enforcement is the chosen, sufficient mechanism.

## Endpoint matrix (2026-06-15)

Legend: **member** = `_load_club_as_member`, **organizer** =
`_load_club_as_organizer`, **self** = scoped to `current_user`, **public** =
intentionally unauthenticated, **token** = capability (invite token).

| Endpoint | Auth | Club guard |
|---|---|---|
| `POST /auth/*` | public | n/a — no club data |
| `GET /healthz` | public | n/a |
| `GET/PATCH /users/me` | self | n/a — own profile only |
| `POST /songs/resolve`, `GET /songs/search` | authed | n/a — external search, no club data |
| `POST /clubs` | authed | creates own club (caller becomes organizer+member) |
| `GET /clubs` | authed | returns only the caller's active memberships |
| `GET /clubs/:id` | authed | **member** |
| `GET /clubs/:id/members` | authed | **member** |
| `PATCH /clubs/:id` | authed | **organizer** |
| `DELETE /clubs/:id/members/:userId` | authed | **organizer** (+ member-of-this-club check on target) |
| `POST /clubs/:id/invites` | authed | **member** (active member may invite) |
| `GET /invites/:token` | public | **token** — minimal preview (name + member count) only |
| `POST /invites/:token/accept` | authed | **token** — join flow (caller is not yet a member by design) |
| `POST /clubs/:id/mixes` | authed | **organizer** |
| `GET /clubs/:id/mixes` | authed | **member** |
| `GET /mixes/:id` | authed | **member** (via mix → club) |
| `PATCH /mixes/:id` | authed | **organizer** (via mix → club) |
| `GET /mixes/:id/playlist` | authed | **member** |
| `GET /mixes/:id/results` | authed | **member** (+ gated to `closed`) |
| `POST /mixes/:id/submissions` | authed | **member** |
| `GET /mixes/:id/submissions/mine` | authed | **member** |
| `GET /mixes/:id/submissions` | authed | **member** (+ gated to `closed`) |
| `POST /mixes/:id/votes` | authed | **member** |
| `GET /mixes/:id/votes/mine` | authed | **member** |
| `POST /submissions/:id/notes` | authed | **member** (via submission → mix → club) |
| `GET /submissions/:id/notes` | authed | **member** |

**Finding: no gaps.** Every endpoint that reads or mutates club-scoped data
enforces membership or organizer, deriving the club from the resource itself.
The two unauthenticated surfaces (`POST /auth/*`, `GET /healthz`) hold no club
data; `GET /invites/:token` is an intentional capability-token preview returning
only a club name and member count.

## Test coverage

Negative (non-member → 403) tests exist on every club-scoped endpoint
(`test_clubs_*`, `test_invites_create`, `test_mixes`, `test_submissions`,
`test_votes`, `test_notes`, `test_results`, `test_playlist`). In addition,
`tests/test_authorization_isolation.py` consolidates the **cross-tenant**
(confused-deputy) case: a legitimate active member of one club is denied on
another club's nested resources, proving membership is checked against the
resource's actual club rather than merely "is the caller a member of
something."

## Known, accepted nuance (not an isolation issue)

The organizer-gated routes (`PATCH /clubs/:id`, `POST /clubs/:id/mixes`,
`PATCH /mixes/:id`, `DELETE /clubs/:id/members/:userId`) use
`_load_club_as_organizer`, which gates solely on `organizer_id` and does not
first assert membership. As a result a **true non-member** of the club receives
the organizer-phrased 403 (`"only the organizer can ..."`) rather than the
member-phrased one. The **status is correct (403) and isolation holds** — no
protected data is returned — but the message slightly over-implies the caller is
a member. This is a cosmetic message-consistency / least-disclosure nit, not a
data-isolation defect, and is intentionally left as-is here to avoid changing
shared auth semantics during the sign-off audit. If tightened later, make
`_load_club_as_organizer` assert membership before the organizer check so true
outsiders get the member-phrased 403 (and update the per-route tests that assert
the organizer message for non-members).
