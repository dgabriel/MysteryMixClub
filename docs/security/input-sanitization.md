# Input Sanitization — User-Supplied Text Fields

Technical-design §9: *"Input sanitization on all text fields (submission notes,
display names)."* Records the MYS-49 audit + hardening of every free-text field.

## Approach: bound on input, escape on render

We deliberately **do not** strip or rewrite HTML server-side. User text is stored
**verbatim** and rendered safely because the React frontend escapes all
interpolated values (there is no `dangerouslySetInnerHTML` / raw-HTML sink in the
codebase). Server-side responsibilities are therefore:

1. **Length-bound** every field (reject oversize input with 422) to prevent
   storage/abuse and keep payloads sane.
2. **Trim** surrounding whitespace on human-entered fields (`strip_whitespace`)
   so " " isn't a meaningful value; URLs are not trimmed.
3. Preserve the exact characters within bounds — a `<script>` payload round-trips
   byte-for-byte and is neutralized at render, not silently mutated on the way in.

All bounds are enforced declaratively via Pydantic `StringConstraints`; a
violation returns **422** with no manual handling.

## Field bounds (2026-06-15, MYS-49)

| Field | Endpoint | strip | min | max |
|---|---|---|---|---|
| `display_name` | `PATCH /users/me` | yes | 1 | 50 |
| club `name` | `POST`/`PATCH /clubs` | yes | 1 | 100 |
| club `description` | `POST`/`PATCH /clubs` | yes | — | 2000 |
| mystery mix `theme` | `POST /clubs/:id/mixes` | yes | 1 | 200 |
| submission `title` / `artist` | `POST /mixes/:id/submissions` | yes | 1 | 500 |
| submission `note` | `POST /mixes/:id/submissions` | yes | — | 280 |
| submission `album` | `POST /mixes/:id/submissions` | yes | — | 500 |
| submission `album_art_url` | `POST /mixes/:id/submissions` | no (URL) | — | 2048 |
| notes `body` | `POST /submissions/:id/notes` | yes | 1 | 280 |
| search `q` | `GET /songs/search` | — | 1 | 200 |
| search `artist` | `GET /songs/search` | — | — | 200 |
| resolve `url` / `thumbnail_url` | `POST /songs/resolve` | no (URL) | — | 2048 |
| resolve `title` / `artist` / `album` | `POST /songs/resolve` | yes | — | 500 |
| resolve `isrc` | `POST /songs/resolve` | yes | — | 32 |

## Changes made (MYS-49)

The audit found most fields already bounded. Two gaps were closed:

- **`club.description`** was `str | None` — **unbounded**. Now bounded to 2000
  chars (trimmed). `ClubUpdate`'s explicit-null validator was preserved:
  `description: null` on PATCH still clears the field; the validator's NOT-NULL
  reject list (`name`, `total_rounds`) is unchanged.
- **`submission.note`** had `max_length=280` but no trim — added
  `strip_whitespace=True` for consistency with the notes-body field. The
  optional display fields `album` (500, trimmed) and `album_art_url` (2048,
  untrimmed) were also bounded since they are client-supplied.
- **`GET /songs/search`** (`q`, `artist`) and **`POST /songs/resolve`** (`url`,
  `title`, `artist`, `isrc`, `album`, `thumbnail_url`) were unbounded. Bounded
  with the same idiom — search terms to 200, resolve text to 500 / isrc 32 /
  URLs 2048 (untrimmed). Submission persistence re-validates the resolved fields
  on `POST /submissions`, but the search/resolve surface is now hardened itself.

## Tests

`backend/tests/test_input_sanitization.py` (30 tests): exact boundary
accept/reject for each field, whitespace-trim behavior (and the URL no-trim
case), the optional-field empty/null cases, regression-locks on the
already-bounded fields, and a verbatim round-trip of a `<script>` payload that
documents the bound-and-escape posture.

## Frontend

No `dangerouslySetInnerHTML` or other raw-HTML rendering exists; React escapes
all interpolated text. Stored user values (names, notes, themes, descriptions)
are therefore safe to render as text. If a raw-HTML render is ever introduced, it
must be paired with sanitization (e.g. DOMPurify) — currently none is needed.
