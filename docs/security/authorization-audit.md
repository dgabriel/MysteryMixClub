# Authorization Audit — Per-League Data Isolation

Technical-design §9: *"Row-level security on PostgreSQL — players can only access
their own league data."* This records the pre-launch audit (MYS-48) of every
authenticated endpoint and the enforcement-mechanism decision.

## Decision: app-layer enforcement (not DB RLS) for v1

Per-league isolation is enforced **at the application layer**, primarily via two
shared helpers in `app/api/routes/leagues.py` (the invite-creation route inlines
an equivalent active-member check rather than calling the helper):

- `_load_league_as_member(league_id, user, db)` → 404 if the league is missing,
  403 if the caller has no active (`removed_at IS NULL`) `league_members` row.
- `_load_league_as_organizer(league_id, user, db)` → 404 if missing, 403 unless
  the caller is the league's `organizer_id`.

**Why app-layer, not Postgres RLS, for v1:**

- Every league-scoped route already derives the league **from the resource**
  (round → `league_id`, submission → round → `league_id`, note → submission →
  round → `league_id`) and then calls a guard. There is no path that trusts a
  client-supplied league id to authorize a differently-owned resource, so there
  is no confused-deputy surface for RLS to backstop.
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

Legend: **member** = `_load_league_as_member`, **organizer** =
`_load_league_as_organizer`, **self** = scoped to `current_user`, **public** =
intentionally unauthenticated, **token** = capability (invite token).

| Endpoint | Auth | League guard |
|---|---|---|
| `POST /auth/*` | public | n/a — no league data |
| `GET /healthz` | public | n/a |
| `GET/PATCH /users/me` | self | n/a — own profile only |
| `POST /songs/resolve`, `GET /songs/search` | authed | n/a — external search, no league data |
| `POST /leagues` | authed | creates own league (caller becomes organizer+member) |
| `GET /leagues` | authed | returns only the caller's active memberships |
| `GET /leagues/:id` | authed | **member** |
| `GET /leagues/:id/members` | authed | **member** |
| `PATCH /leagues/:id` | authed | **organizer** |
| `DELETE /leagues/:id/members/:userId` | authed | **organizer** (+ member-of-this-league check on target) |
| `POST /leagues/:id/invites` | authed | **member** (active member may invite) |
| `GET /invites/:token` | public | **token** — minimal preview (name + member count) only |
| `POST /invites/:token/accept` | authed | **token** — join flow (caller is not yet a member by design) |
| `POST /leagues/:id/rounds` | authed | **organizer** |
| `GET /leagues/:id/rounds` | authed | **member** |
| `GET /rounds/:id` | authed | **member** (via round → league) |
| `PATCH /rounds/:id` | authed | **organizer** (via round → league) |
| `GET /rounds/:id/playlist` | authed | **member** |
| `GET /rounds/:id/results` | authed | **member** (+ gated to `closed`) |
| `POST /rounds/:id/submissions` | authed | **member** |
| `GET /rounds/:id/submissions/mine` | authed | **member** |
| `GET /rounds/:id/submissions` | authed | **member** (+ gated to `closed`) |
| `POST /rounds/:id/votes` | authed | **member** |
| `GET /rounds/:id/votes/mine` | authed | **member** |
| `POST /submissions/:id/notes` | authed | **member** (via submission → round → league) |
| `GET /submissions/:id/notes` | authed | **member** |

**Finding: no gaps.** Every endpoint that reads or mutates league-scoped data
enforces membership or organizer, deriving the league from the resource itself.
The two unauthenticated surfaces (`POST /auth/*`, `GET /healthz`) hold no league
data; `GET /invites/:token` is an intentional capability-token preview returning
only a league name and member count.

## Test coverage

Negative (non-member → 403) tests exist on every league-scoped endpoint
(`test_leagues_*`, `test_invites_create`, `test_rounds`, `test_submissions`,
`test_votes`, `test_notes`, `test_results`, `test_playlist`). In addition,
`tests/test_authorization_isolation.py` consolidates the **cross-tenant**
(confused-deputy) case: a legitimate active member of one league is denied on
another league's nested resources, proving membership is checked against the
resource's actual league rather than merely "is the caller a member of
something."

## Known, accepted nuance (not an isolation issue)

The organizer-gated routes (`PATCH /leagues/:id`, `POST /leagues/:id/rounds`,
`PATCH /rounds/:id`, `DELETE /leagues/:id/members/:userId`) use
`_load_league_as_organizer`, which gates solely on `organizer_id` and does not
first assert membership. As a result a **true non-member** of the league receives
the organizer-phrased 403 (`"only the organizer can ..."`) rather than the
member-phrased one. The **status is correct (403) and isolation holds** — no
protected data is returned — but the message slightly over-implies the caller is
a member. This is a cosmetic message-consistency / least-disclosure nit, not a
data-isolation defect, and is intentionally left as-is here to avoid changing
shared auth semantics during the sign-off audit. If tightened later, make
`_load_league_as_organizer` assert membership before the organizer check so true
outsiders get the member-phrased 403 (and update the per-route tests that assert
the organizer message for non-members).
