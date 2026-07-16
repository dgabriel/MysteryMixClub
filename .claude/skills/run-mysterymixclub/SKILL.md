---
name: run-mysterymixclub
description: Build, run, and drive the MysteryMixClub web app (FastAPI backend + React/Vite frontend). Use when asked to start the app, launch the local dev stack, test a feature/PR branch locally, take a screenshot of the UI, or drive a page interaction (fill a form, click through a flow, check console errors).
---

MysteryMixClub is a browser-driven web app: FastAPI backend (`backend/`,
port 8000) + React/Vite frontend (`frontend/`, port 5173), backed by
Postgres via Docker. For agent/automated use, drive the running page with
the Playwright REPL at `.claude/skills/run-mysterymixclub/driver.mjs` — this
environment has no `chromium-cli`, so the driver fills that role directly.

All paths below are relative to the repo root.

## Prerequisites

Already verified present in this environment — Docker Desktop must be
*running* (`open -a Docker`, then poll `docker info` until it succeeds; a
fresh install can take ~30s to come up):

```bash
git --version      # 2.50+
python3 --version   # 3.11+ (repo's backend/.venv uses whatever python3 resolves to)
node --version      # 20+
docker --version && docker info >/dev/null   # daemon must be running
```

The driver needs its own Playwright + Chromium (not part of the app's own
deps — kept out of `frontend/package.json` on purpose):

```bash
(cd .claude/skills/run-mysterymixclub && npm install)   # installs playwright
npx --prefix .claude/skills/run-mysterymixclub playwright install chromium
```

## Setup + Build

The repo ships `scripts/dev-up.sh`, which installs deps, applies
migrations, and launches Postgres + API + web in one shot — **but it
unconditionally `git checkout develop` first, with no flag to skip.** Fine
for "just run the app." Wrong for testing an unmerged feature/PR branch,
which is the more common ask. Two paths:

### Path A — running `develop` (or you don't care which branch)

```bash
./scripts/dev-up.sh          # checks out develop, sets up env, starts everything
./scripts/dev-up.sh logs     # tail backend + frontend logs
./scripts/dev-up.sh stop     # stop the API + web it started (Postgres keeps running)
```

Then skip to "Run (agent path)" below — the stack is already up.

### Path B — testing a feature/PR branch (stay on your branch)

Don't run `dev-up.sh`. Replicate its steps by hand, without the branch switch:

```bash
docker compose up -d db
timeout=30; until docker compose exec -T db pg_isready -U mmc -d mysterymixclub >/dev/null 2>&1; do
  sleep 1; timeout=$((timeout-1)); [ $timeout -le 0 ] && { echo "postgres timeout"; exit 1; }
done

cd backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"
.venv/bin/alembic upgrade head
cd ..

mkdir -p .dev/pids .dev/logs
( cd backend && nohup .venv/bin/uvicorn app.main:app --reload --port 8000 \
    </dev/null >../.dev/logs/backend.log 2>&1 & echo $! >../.dev/pids/backend.pid )

( cd frontend && npm install --no-fund --no-audit )
( cd frontend && nohup npm run dev </dev/null >../.dev/logs/frontend.log 2>&1 & echo $! >../.dev/pids/frontend.pid )

timeout=30; until curl -fsS http://127.0.0.1:8000/api/v1/healthz >/dev/null 2>&1; do
  sleep 1; timeout=$((timeout-1)); [ $timeout -le 0 ] && { echo "api timeout"; exit 1; }
done
timeout=30; until curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; do
  sleep 1; timeout=$((timeout-1)); [ $timeout -le 0 ] && { echo "web timeout"; exit 1; }
done
```

`backend/.env` and `frontend/.env.local` are gitignored and branch-independent
— `dev-up.sh`'s `ensure_env`/`ensure_frontend_env` steps created them once;
they don't need recreating per branch. If they're missing (fresh clone),
run `./scripts/dev-up.sh check` first to get `dev-up.sh` to create them,
then `git checkout -` back to your branch before doing Path B.

Stop what Path B started with:

```bash
kill "$(cat .dev/pids/backend.pid)" "$(cat .dev/pids/frontend.pid)" 2>/dev/null
rm -f .dev/pids/backend.pid .dev/pids/frontend.pid
```

## Run (agent path)

With the stack up (either path), drive the page via the REPL driver. It
has no `tmux`/`timeout` dependency — pipe a heredoc script to stdin for a
one-shot run:

```bash
node .claude/skills/run-mysterymixclub/driver.mjs <<'EOF'
launch
nav /
wait-for text=MysteryMixClub
ss 01-landing
console --errors
quit
EOF
```

Screenshots land in `/tmp/shots/` (override: `SCREENSHOT_DIR`). The driver
targets `http://127.0.0.1:5173` by default (override: `APP_URL`).

If `tmux` *is* available in your environment, wrap it for iterative,
one-command-at-a-time use instead of a single heredoc:

```bash
tmux new-session -d -s mmc -x 200 -y 50
tmux send-keys -t mmc 'node .claude/skills/run-mysterymixclub/driver.mjs' Enter
until tmux capture-pane -t mmc -p | grep -q 'driver>'; do sleep 0.2; done
tmux send-keys -t mmc 'launch' Enter
tmux capture-pane -t mmc -p
```

### Commands

| command | what it does |
|---|---|
| `launch` | launch headless Chromium, open a page |
| `nav <path-or-url>` | navigate; bare paths resolve against `APP_URL` |
| `ss [name]` | screenshot → `/tmp/shots/<name>.png` |
| `click <css-sel>` | Playwright `.click()` |
| `click-text <text>` | click first element containing text |
| `fill <css-sel> <value>` | fill an input (goes through React's onChange — see Gotchas) |
| `press <key>` | keyboard press, e.g. `Enter` |
| `wait-for <css-sel>` or `text=<text>` | wait up to 15s |
| `eval <js>` | evaluate in page, print JSON |
| `text [css-sel]` | print `innerText` (body if no selector) |
| `url` | print current page URL |
| `console [--errors]` | print captured console/pageerror log |
| `quit` | close browser, exit |

### Verified golden path (ran this session)

Request-access → confirmation screen, the flow every other feature sits
behind:

```bash
node .claude/skills/run-mysterymixclub/driver.mjs <<'EOF'
launch
nav /
wait-for text=MysteryMixClub
fill input[type="email"] driver-smoke-test@example.com
click-text Send sign-in link
wait-for text=check your email
ss 02-check-email
quit
EOF
```

Produces a real "check your email" screen. To go further and actually
complete sign-in (get a magic-link token), see Gotchas — `RESEND_API_KEY`.

## Run (human path)

```bash
./scripts/dev-up.sh   # or Path B above for a feature branch
```

Then open `http://127.0.0.1:5173` in a real browser. Stop with
`./scripts/dev-up.sh stop` or the manual `kill` above.

## Test

```bash
cd backend && .venv/bin/pytest        # backend
cd frontend && npm run test           # frontend (vitest)
cd frontend && npm run typecheck && npm run lint
cd backend && .venv/bin/mypy app      # NOT in pre-push hook — CI-only, run it yourself
```

## Gotchas

- **`dev-up.sh` force-checks-out `develop`.** No flag to skip. Testing an
  unmerged feature/PR branch needs Path B above, not the script.
- **Piped/heredoc stdin + `rl.on('line', async …)` races.** Node's
  `readline` emits every buffered `'line'` event in the same tick
  regardless of whether the previous async handler finished — a `nav`
  right after `launch` in a heredoc would fire before `launch`'s await
  resolved (`ERROR: launch first`, seen firsthand). Fixed in the driver
  with `for await (const line of rl)`, which pulls one line at a time.
  If you extend the driver, keep that loop shape.
- **`RESEND_API_KEY` set locally → no magic link in the log.**
  `backend/.env` here has a real Resend key, so the backend actually
  calls the Resend API instead of printing the link to
  `.dev/logs/backend.log` (the documented no-key dev fallback). To get a
  loggable magic link for a full sign-in-through-verify test, temporarily
  launch backend with that var unset for the process
  (`env -u RESEND_API_KEY .venv/bin/uvicorn …`) rather than editing
  `.env` — don't send real email as a side effect of a smoke test.
- **Invite-only signup hides whether an email is invited.** Submitting
  any email — invited or not — returns the same "check your email"
  screen (no enumeration leak, [[project_invite-only-login]]). An
  uninvited email produces **no** magic link at all (not even a log
  line) — that's correct behavior, not a driver failure. Use a seeded
  admin email (`SEED_ADMIN_EMAILS` in `backend/.env`) or generate a
  platform invite (`POST /admin/invites`, MYS-182) to reach a real
  signup.
- **No `tmux`/`timeout` on this machine.** The heredoc-pipe pattern above
  is the fallback that doesn't need either; use it unless the executing
  environment actually has them.
- **`GET /api/v1/auth/refresh` 401 on every fresh page load** is expected
  console noise for an unauthenticated session, not a bug — the frontend
  probes for an existing session on mount.

## Troubleshooting

- **`Docker is installed but the daemon isn't running`**: `open -a Docker`
  (macOS), then poll: `until docker info >/dev/null 2>&1; do sleep 2; done`.
- **`alembic: Can't locate revision identified by '<hash>'`**: the local
  Postgres volume's migration history belongs to a different branch than
  the one currently checked out (e.g. `dev-up.sh` switched you to
  `develop` out from under a feature branch's already-applied migration).
  Check out the branch whose migrations match, then `alembic upgrade head`
  again — don't drop the volume to force it.
- **`npx playwright install chromium` warns about missing project deps
  and appears to do nothing**: happens when playwright isn't a real
  dependency in that directory yet. Run `npm install` in
  `.claude/skills/run-mysterymixclub/` first (see Prerequisites), then
  install chromium from inside that directory.
