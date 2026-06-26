# Manual Test Findings — running log

Drop findings here as you test. When you're ready, hand it to Claude and it will
batch-create Linear issues (team **MysteryMixClub**, project **MysteryMixClub MVP**)
from each entry. Delete or strike rows once filed.

Each entry maps to a Linear issue:
- **Title** → issue title
- **Priority** → Urgent / High / Medium / Low (maps to Linear priority)
- **Screen** → where it happened (a label/context line)
- **Steps / Expected / Actual** → issue description

Fast option: if you're moving quick, just write a one-line bullet under
"Quick capture" and Claude will expand it into the full shape before filing —
the structured template below is only there if you want to be precise.

---

## Quick capture (one line each)

- [P?] <screen> — <what's wrong>

### Filed to Linear — 2026-06-21

- ~~[P1] round submitting — auto-open voting once every player has submitted~~ → **MYS-69** (combined w/ auto-close)
- ~~[P1] round voting — button with "..." label should NOT appear~~ → **MYS-66**
- ~~[P2] round voting — highlight which songs the player voted for~~ → **MYS-70**
- ~~[P2] round voting — don't allow selecting your own song~~ → **MYS-73** (blocked by MYS-68)
- ~~[P2] round voting — make their submission obvious~~ → **MYS-74** (blocked by MYS-68)
- ~~[P2] round voting — don't show others' notes while voting is open~~ → **MYS-67**
- ~~[P2] round voting — auto-close + advance once everyone has voted~~ → **MYS-69** (combined w/ auto-open)
- ~~[P2] round results — winning songs above most noted~~ → **MYS-71** (kept Most Noted on top per decision)
- ~~[P2] round results — collapsible notes under songs~~ → **MYS-72**
### Filed to Linear — 2026-06-22 (staging)

- ~~[P3] round - remove "it's up next in the queue.", keep "this round hasn't opened yet"~~ → **MYS-94**
- ~~[P2] round - "Opening..." button stays after the round opens~~ → **MYS-95**
- ~~[P2] round and league - non-admins: poll/websocket to refresh state every ~30s~~ → **MYS-96**
- ~~[P2] account - change name, or leave league~~ → **MYS-97** (leave league) + **MYS-61** (change name)
- ~~[P2] league - add another player as admin, or remove player~~ → **MYS-98** (remove) + **MYS-99** (co-admin)
- ~~[P1] search paste link - wrong song selected (Serpentskirt vs Serpents, track 2v05RhwIQx3zbN8O72Ff69)~~ → **MYS-100**
- ~~[P2] round submit - "X out of Y players have submitted songs"~~ → **MYS-101**
- ~~[P2] league - round card should say "X out of Y players have submitted songs"~~ → **MYS-101**
- ~~[P1] spotify playlist - error generating "spotify couldn't create the playlist"~~ → **MYS-90** (fixed)
- ~~[P2] voting - "X out of Y players have voted or noted, and Z are just vibing"~~ → **MYS-102**
- ~~[P4] spotify playlist - after create, auto-redirect to the new playlist~~ → **MYS-103**
- ~~[P2] profile page - add the user email address~~ → fixed on `feature/mys-129-130-profile-nav` (read-only email line on profile)
- ~~[P1] round - duplicated navigation bar~~ → fixed (round screen rendered a 2nd TopNav on top of AuthedLayout's; removed)
- ~~[P1] round - Remove League from navigation bar, replace with a link to the league above the round name.  Use the league's actual name, not just "League"~~ → fixed (named "← {league.name}" link above the round title; nav back-link dropped)
- ~~[P3] nav bar - add a bit of rust. too monotne, even for us~~ → fixed (brand mark now carries its Rust dot; documented as an official style-guide exception so it doesn't spend a screen's one-Rust budget)
- ~~[P1] git skill - create clear best-practice-based guidelines for git higene, and do not get into weird states ever. make sure those guidelines are persisted and referred to every time you begin a task.~~ → fixed (new `docs/git-hygiene.md` canonical guide; wired into CLAUDE.md "On Every Session Start" + Docs Map + Session Checklist so it's read before any git work; backed by a persistent memory)
- ~~[P1] round voting - vibe players must be able to leave notes and submit them, even if voting if off~~ → **MYS-132**
- ~~[P1] round closed - The playlist is no longer visible!~~ → **MYS-133**
- enabler added: **MYS-68** — voting playlist marks the caller's own entry (blocks MYS-73, MYS-74)

---

## Detailed findings

### 1. <short title>
- **Priority:** Medium
- **Screen:** League home (closed round card)
- **Steps:**
  1.
  2.
- **Expected:**
- **Actual:**
- **Notes / screenshot:**

### 2.
- **Priority:**
- **Screen:**
- **Steps:**
- **Expected:**
- **Actual:**
- **Notes:**
