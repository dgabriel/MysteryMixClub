#!/usr/bin/env bash
#
# MysteryMixClub — one-command local dev setup + run (macOS & Linux).
#
# What it does, in order:
#   1. Checks for the tools a dev needs (git, Python 3.11+, Node 20+, Docker) and
#      offers to install anything missing via the system package manager
#      (Homebrew on macOS; apt/dnf/pacman/zypper on Linux). Docker must already be
#      installed and running — it'll tell you how if not.
#   2. Switches you to the 'develop' branch (the integration branch this app runs
#      from) and pulls the latest code on it.
#   3. Creates backend/.env from .env.example (with a generated SECRET_KEY) if absent.
#   4. Stops any dev instance this script previously started, then spins up a fresh
#      one: Postgres (docker compose) + API (uvicorn) + web (vite), in the
#      background with logs under .dev/logs/.
#
# Optional integrations — fill these into backend/.env to light them up:
#
#   Spotify (per-user playlist creation — MYS-83). Until these are set, the app
#   runs fine but Spotify playlist export is disabled.
#     1. Sign in at https://developer.spotify.com/dashboard and "Create app".
#     2. Copy the Client ID and Client Secret into SPOTIFY_CLIENT_ID /
#        SPOTIFY_CLIENT_SECRET.
#     3. In the app's settings, add this exact Redirect URI (Spotify rejects
#        "localhost" — you must use the loopback IP):
#          http://127.0.0.1:8000/api/v1/spotify/callback
#        and put the same value in SPOTIFY_REDIRECT_URI.
#
#   Resend (magic-link sign-in + round-notification email). Until RESEND_API_KEY
#   is set, no email is sent — in dev the magic-link is printed to the API log
#   (.dev/logs/backend.log) so you can still sign in.
#     1. Create an account at https://resend.com and verify a sending domain (or
#        use their onboarding test domain).
#     2. Create an API key at https://resend.com/api-keys and paste it into
#        RESEND_API_KEY.
#
# Usage:
#   scripts/dev-up.sh          # set up + (re)start the full stack  [default]
#   scripts/dev-up.sh check    # only verify/install the tools, start nothing
#   scripts/dev-up.sh stop     # stop the API + web this script started
#   scripts/dev-up.sh logs     # tail the API + web logs
#   ASSUME_YES=1 scripts/dev-up.sh   # don't prompt; say yes to installs
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DEV_DIR="$REPO_ROOT/.dev"
PID_DIR="$DEV_DIR/pids"
LOG_DIR="$DEV_DIR/logs"
ASSUME_YES="${ASSUME_YES:-0}"

# --- output helpers -------------------------------------------------------- #
if [ -t 1 ]; then
  BOLD=$(tput bold || true); RED=$(tput setaf 1 || true); GRN=$(tput setaf 2 || true)
  YEL=$(tput setaf 3 || true); BLU=$(tput setaf 4 || true); RST=$(tput sgr0 || true)
else
  BOLD= RED= GRN= YEL= BLU= RST=
fi
info() { printf '%s %s\n' "${BLU}==>${RST}" "$*"; }
ok()   { printf '%s %s\n' "${GRN}✓${RST}" "$*"; }
warn() { printf '%s %s\n' "${YEL}!${RST}" "$*"; }
die()  { printf '%s\n' "${RED}✗ $*${RST}" >&2; exit 1; }

confirm() { # confirm "prompt"  -> 0 yes / 1 no  (default No, unless ASSUME_YES=1)
  [ "$ASSUME_YES" = "1" ] && return 0
  local reply; read -r -p "$1 [y/N] " reply || true
  case "$reply" in [yY] | [yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

have() { command -v "$1" >/dev/null 2>&1; }

ver_ge() { # ver_ge HAVE NEED -> 0 if HAVE >= NEED (dotted versions)
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# --- platform detection ---------------------------------------------------- #
case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux)  OS=linux ;;
  *) die "Unsupported OS '$(uname -s)' — this script supports macOS and Linux only." ;;
esac

PKG=""
detect_pkg() {
  if [ "$OS" = mac ]; then PKG=brew; return; fi
  for m in apt-get dnf pacman zypper; do have "$m" && { PKG="$m"; return; }; done
}

SUDO=""
[ "$OS" = linux ] && [ "$(id -u)" -ne 0 ] && SUDO="sudo"

# --- tool installation ----------------------------------------------------- #
ensure_brew() {
  have brew && return
  warn "Homebrew is required to install tools on macOS."
  confirm "Install Homebrew now?" || die "Homebrew required — see https://brew.sh, then re-run."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
  [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
}

pkg_install() { # pkg_install "Human Name" brew_pkg apt_pkg dnf_pkg pacman_pkg
  local human="$1" brewp="$2" aptp="$3" dnfp="$4" pacp="$5"
  [ -n "$PKG" ] || die "No supported package manager found — install $human manually, then re-run."
  confirm "Install $human via ${PKG}?" || die "$human is required."
  case "$PKG" in
    brew)    brew install $brewp ;;
    apt-get) $SUDO apt-get update -y && $SUDO apt-get install -y $aptp ;;
    dnf)     $SUDO dnf install -y $dnfp ;;
    pacman)  $SUDO pacman -Sy --noconfirm $pacp ;;
    zypper)  $SUDO zypper install -y $dnfp ;;
  esac
}

ensure_git() {
  have git && { ok "git $(git --version | awk '{print $3}')"; return; }
  pkg_install "git" git git git git
}

ensure_curl() {
  have curl && return
  pkg_install "curl" curl curl curl curl
}

# Resolved Python interpreter (Homebrew installs python as `python3.12`, not an
# unversioned `python3`, so we can't assume the latter exists). Set by find_python.
PYTHON_BIN=""
find_python() {
  local c v
  for c in python3 python3.13 python3.12 python3.11; do
    have "$c" || continue
    v="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
    if ver_ge "$v" 3.11; then PYTHON_BIN="$c"; return 0; fi
  done
  return 1
}

ensure_python() {
  if find_python; then ok "Python $("$PYTHON_BIN" -V 2>&1 | awk '{print $2}') ($PYTHON_BIN)"; return; fi
  pkg_install "Python 3.11+" "python@3.12" "python3 python3-venv python3-pip" \
    "python3 python3-pip" "python python-pip"
  find_python || die "Python 3.11+ still not available after install — please install it manually."
  ok "Python $("$PYTHON_BIN" -V 2>&1 | awk '{print $2}') ($PYTHON_BIN)"
}

install_node_via_nvm() {
  export NVM_DIR="$HOME/.nvm"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    info "Installing nvm (Node version manager) into ~/.nvm…"
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  fi
  # nvm's functions aren't written for `set -e`; relax it while we source + use.
  set +e
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install 20
  nvm use 20
  set -e
}

ensure_node() {
  if have node && ver_ge "$(node -v | sed 's/^v//')" 20; then
    ok "Node $(node -v)"; return
  fi
  if [ "$OS" = mac ]; then
    # Homebrew's current Node formula is 20+.
    pkg_install "Node.js 20+" node "" "" ""
  else
    # Linux distro packages are routinely stuck on Node 18, so go straight to
    # nvm — user-space, no sudo, always a real 20+.
    warn "Installing Node 20 via nvm (user-space, no sudo)…"
    install_node_via_nvm
  fi
  have node && ver_ge "$(node -v | sed 's/^v//')" 20 \
    || die "Node 20+ still not available — please install it manually."
  ok "Node $(node -v)"
}

ensure_docker() {
  have docker || die "Docker not found. Install it, then re-run:
    macOS:  https://docs.docker.com/desktop/install/mac-install/   (or 'brew install --cask docker')
    Linux:  https://docs.docker.com/engine/install/   (then add yourself to the 'docker' group)"
  docker compose version >/dev/null 2>&1 \
    || die "Docker is present but the Compose v2 plugin is missing — update Docker, then re-run."
  docker info >/dev/null 2>&1 \
    || die "Docker is installed but the daemon isn't running. Start Docker Desktop, or on Linux: 'sudo systemctl start docker'. Then re-run."
  ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) (daemon running)"
}

# --- repo + env ------------------------------------------------------------ #
checkout_develop() {
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
  [ "$branch" = "develop" ] && { ok "On 'develop'."; return; }
  info "Switching to 'develop' (was on '${branch:-unknown}')…"
  git checkout develop || die "Couldn't switch to 'develop' — commit or stash your changes, then re-run."
}

pull_latest() {
  if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    info "Pulling latest on $(git rev-parse --abbrev-ref HEAD)…"
    git pull --ff-only || warn "Couldn't fast-forward (local changes or diverged?) — continuing with current checkout."
  else
    warn "No upstream tracking branch — skipping git pull."
  fi
}

set_env_var() { # set_env_var FILE KEY VALUE — replace KEY=… or append
  local f="$1" k="$2" v="$3"
  if grep -qE "^${k}=" "$f"; then
    awk -v k="$k" -v v="$v" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
  else
    printf '%s=%s\n' "$k" "$v" >>"$f"
  fi
}

ensure_env() {
  local env="$REPO_ROOT/backend/.env"
  if [ -f "$env" ]; then ok "backend/.env present"; return; fi
  info "Creating backend/.env from .env.example…"
  cp "$REPO_ROOT/.env.example" "$env"
  # Use the 127.0.0.1 loopback IP (not "localhost") everywhere: Spotify's OAuth
  # rejects "localhost" redirect URIs, so the whole dev stack stays on the IP to
  # keep origins/cookies consistent with the Spotify callback.
  set_env_var "$env" DATABASE_URL "postgresql+asyncpg://mmc:mmc@127.0.0.1:5432/mysterymixclub"
  set_env_var "$env" SECRET_KEY "$("${PYTHON_BIN:-python3}" -c 'import secrets;print(secrets.token_urlsafe(64))')"
  set_env_var "$env" ENVIRONMENT "development"
  set_env_var "$env" APP_BASE_URL "http://127.0.0.1:5173"
  set_env_var "$env" API_BASE_URL "http://127.0.0.1:8000"
  set_env_var "$env" SPOTIFY_REDIRECT_URI "http://127.0.0.1:8000/api/v1/spotify/callback"
  # Local email sends through Resend (if RESEND_API_KEY is set) must come from a
  # sender Resend accepts without a verified domain. onboarding@resend.dev works,
  # but only delivers to your own Resend signup email until the domain is verified.
  set_env_var "$env" EMAIL_FROM "onboarding@resend.dev"
  ok "backend/.env created with local defaults + a generated SECRET_KEY"
}

ensure_frontend_env() {
  # frontend/.env.local is gitignored, so a fresh clone won't have it and the
  # app falls back to localhost:8000. Point the browser at 127.0.0.1 so origins
  # and the session cookie stay consistent across the Spotify OAuth redirect.
  local fenv="$REPO_ROOT/frontend/.env.local"
  if [ -f "$fenv" ]; then ok "frontend/.env.local present"; return; fi
  info "Creating frontend/.env.local…"
  printf '%s\n' "VITE_API_BASE_URL=http://127.0.0.1:8000" >"$fenv"
  ok "frontend/.env.local created (API base on 127.0.0.1)"
}

ensure_hooks() {
  if [ ! -d "$REPO_ROOT/node_modules" ]; then
    info "Installing git hooks (husky)…"
    ( cd "$REPO_ROOT" && npm install --no-fund --no-audit )
  fi
}

# --- process lifecycle ----------------------------------------------------- #
stop_instance() {
  local stopped=0 name pf pid
  for name in backend frontend; do
    pf="$PID_DIR/$name.pid"
    [ -f "$pf" ] || continue
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      info "Stopping running $name (pid $pid)…"
      pkill -P "$pid" 2>/dev/null || true   # reap children (uvicorn reloader, vite)
      kill "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -9 "$pid" 2>/dev/null || true
      stopped=1
    fi
    rm -f "$pf"
  done
  [ "$stopped" = 1 ] && ok "Stopped the previous instance."
  return 0
}

start_db() {
  info "Starting Postgres (docker compose)…"
  ( cd "$REPO_ROOT" && docker compose up -d db )
  info "Waiting for Postgres to accept connections…"
  for _ in $(seq 1 30); do
    if ( cd "$REPO_ROOT" && docker compose exec -T db pg_isready -U mmc -d mysterymixclub >/dev/null 2>&1 ); then
      ok "Postgres ready on localhost:5432"
      return
    fi
    sleep 1
  done
  die "Postgres didn't become ready in time — check 'docker compose logs db'."
}

start_backend() {
  local venv="$REPO_ROOT/backend/.venv"
  [ -d "$venv" ] || { info "Creating Python venv…"; "${PYTHON_BIN:-python3}" -m venv "$venv"; }
  info "Installing backend dependencies…"
  "$venv/bin/pip" install -q --upgrade pip
  "$venv/bin/pip" install -q -e "$REPO_ROOT/backend[dev]"
  info "Applying database migrations…"
  ( cd "$REPO_ROOT/backend" && "$venv/bin/alembic" upgrade head )
  info "Starting API (uvicorn) on :8000…"
  ( cd "$REPO_ROOT/backend" && nohup "$venv/bin/uvicorn" app.main:app --reload --port 8000 \
      >"$LOG_DIR/backend.log" 2>&1 & echo $! >"$PID_DIR/backend.pid" )
}

start_frontend() {
  info "Installing frontend dependencies…"
  ( cd "$REPO_ROOT/frontend" && npm install --no-fund --no-audit )
  info "Starting web (vite) on :5173…"
  ( cd "$REPO_ROOT/frontend" && nohup npm run dev >"$LOG_DIR/frontend.log" 2>&1 & echo $! >"$PID_DIR/frontend.pid" )
}

wait_for_api() {
  info "Waiting for the API to answer…"
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/api/v1/healthz >/dev/null 2>&1; then
      ok "API healthy at http://127.0.0.1:8000"
      return
    fi
    sleep 1
  done
  warn "API hasn't answered yet — check .dev/logs/backend.log (it may still be starting)."
}

summary() {
  printf '\n%s\n' "${BOLD}${GRN}MysteryMixClub dev stack is up.${RST}"
  cat <<EOF

  Web   : http://127.0.0.1:5173
  API   : http://127.0.0.1:8000   (docs: /docs, health: /api/v1/healthz)
  DB    : postgres://mmc:mmc@127.0.0.1:5432/mysterymixclub

  Logs  : .dev/logs/backend.log , .dev/logs/frontend.log
          tail with: scripts/dev-up.sh logs
  Stop  : scripts/dev-up.sh stop        (Postgres keeps running; 'docker compose stop db' to stop it)
  Sign-in is magic-link based; in dev (no RESEND_API_KEY) the link is printed to the API log.
  Spotify playlist export needs SPOTIFY_CLIENT_ID/SECRET in backend/.env (see top of this script).
EOF
}

# --- entrypoint ------------------------------------------------------------ #
mkdir -p "$PID_DIR" "$LOG_DIR"
cmd="${1:-up}"

case "$cmd" in
  stop | down)
    stop_instance
    info "Done. (Postgres left running — 'docker compose stop db' to stop it too.)"
    exit 0
    ;;
  logs)
    [ -d "$LOG_DIR" ] && ls "$LOG_DIR"/*.log >/dev/null 2>&1 || die "No logs yet — run 'scripts/dev-up.sh' first."
    exec tail -n 50 -F "$LOG_DIR"/*.log
    ;;
  check)
    printf '%s\n\n' "${BOLD}MysteryMixClub — tool check${RST}"
    detect_pkg
    [ "$OS" = mac ] && ensure_brew
    ensure_git; ensure_curl; ensure_python; ensure_node; ensure_docker
    ok "All required tools are present."
    exit 0
    ;;
  up | "")
    : # fall through
    ;;
  *)
    die "Usage: scripts/dev-up.sh [up|check|stop|logs]"
    ;;
esac

printf '%s\n\n' "${BOLD}MysteryMixClub — local dev setup${RST}"
detect_pkg
[ "$OS" = mac ] && ensure_brew

info "Checking tools…"
ensure_git
ensure_curl
ensure_python
ensure_node
ensure_docker

checkout_develop
pull_latest
ensure_env
ensure_frontend_env
ensure_hooks

info "Restarting the dev instance…"
stop_instance
start_db
start_backend
start_frontend
wait_for_api
summary
