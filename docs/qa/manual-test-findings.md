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
- enabler added: **MYS-68** — voting playlist marks the caller's own entry (blocks MYS-73, MYS-74)
- [P2] spotify playlist — playlist title should be "MysteryMixClub: League Name, Round theme" → **MYS-86**
- [P1] spotify playlist - login should be a pop up or modal, not a whole page redirect → **MYS-85**

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
