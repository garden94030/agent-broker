#!/bin/sh
# Mounted at /opt/start-openab.sh in the openab service on Zeabur (Claude variant).
# v6 - switch from Gemini agent to Claude (claude-agent-acp) + Discord.
set -e

missing=""
for v in DISCORD_BOT_TOKEN OPENAB_AUTH_TOKEN GEMINI_API_KEY GITHUB_TOKEN GITHUB_REPO_AI GITHUB_REPO_PLA; do
  eval "val=\$$v"
  [ -z "$val" ] && missing="$missing $v"
done
if [ -n "$missing" ]; then
  echo "openab: missing required env vars:$missing"
  exec sleep infinity
fi

case "$OPENAB_AUTH_TOKEN" in
  sk-ant-oat*) export CLAUDE_CODE_OAUTH_TOKEN="$OPENAB_AUTH_TOKEN" ;;
  sk-ant-*)    export ANTHROPIC_API_KEY="$OPENAB_AUTH_TOKEN" ;;
  *)
    export ANTHROPIC_API_KEY="$OPENAB_AUTH_TOKEN"
    export ANTHROPIC_BASE_URL="https://hnd1.aihub.zeabur.ai"
    export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
    ;;
esac

if ! command -v python3 >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  echo "openab: installing python3 + git"
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y --no-install-recommends python3 python3-pip git ca-certificates >/dev/null 2>&1 \
    || apk add --no-cache python3 py3-pip git ca-certificates 2>/dev/null \
    || echo "openab: WARN failed to install python3/git"
fi

python3 -m pip install --quiet --break-system-packages youtube-transcript-api 2>/dev/null \
  || python3 -m pip install --quiet youtube-transcript-api 2>/dev/null \
  || echo "openab: WARN youtube-transcript-api install failed (captions disabled)"

git config --global --add safe.directory '*' 2>/dev/null || true
mkdir -p /home/node
su -p -s /bin/sh node -c "git config --global --add safe.directory '*'" 2>/dev/null || true

REPO_AI_DIR="${REPO_DIR_AI:-/home/node/repo_ai}"
REPO_PLA_DIR="${REPO_DIR_PLA:-/home/node/repo_pla}"
CONFIG_DIR="/home/node/.config/openab"
CONFIG_FILE="$CONFIG_DIR/config.toml"

mkdir -p "$CONFIG_DIR"

GIT_USER_NAME="${GIT_USER_NAME:-openab-bot}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-openab-bot@users.noreply.github.com}"

clone_or_refresh() {
  dir="$1"; repo="$2"
  url="https://${GITHUB_TOKEN}@github.com/${repo}.git"
  if [ ! -d "$dir/.git" ]; then
    rm -rf "$dir"
    git clone --depth 50 "$url" "$dir" || return 1
  else
    git -C "$dir" remote set-url origin "$url" 2>/dev/null || true
    git -C "$dir" fetch --depth 50 origin || true
    git -C "$dir" reset --hard origin/HEAD 2>/dev/null || true
  fi
  git -C "$dir" config user.name "$GIT_USER_NAME"
  git -C "$dir" config user.email "$GIT_USER_EMAIL"
}

clone_or_refresh "$REPO_AI_DIR" "$GITHUB_REPO_AI"
clone_or_refresh "$REPO_PLA_DIR" "$GITHUB_REPO_PLA" || echo "openab: WARN PLA clone failed; continuing"

# Write secret-scan pre-commit hook to /opt and install into both repos.
cat > /opt/secret-scan-hook.sh <<'HOOK_EOF'
#!/bin/sh
set -e
PATTERNS='AIzaSy[A-Za-z0-9_-]{30,}|github_pat_[A-Za-z0-9_]{60,}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|ghs_[A-Za-z0-9]{30,}|sk-ant-[A-Za-z0-9_-]{50,}|sk-proj-[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|MT[A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}|[0-9]{8,}:[A-Za-z0-9_-]{35}'
DIFF=$(git diff --cached --no-color -U0 2>/dev/null || true)
ADDED=$(printf '%s\n' "$DIFF" | grep -E '^\+[^+]' || true)
[ -z "$ADDED" ] && exit 0
FOUND=$(printf '%s\n' "$ADDED" | grep -nE "$PATTERNS" 2>/dev/null || true)
if [ -n "$FOUND" ]; then
  printf '\nopenab pre-commit: BLOCKED, staged content contains potential secrets.\n' >&2
  printf '%s\n' "$FOUND" | head -5 | awk '{gsub(/[A-Za-z0-9_-]{12,}/, "[REDACTED]"); print "  " $0}' >&2
  exit 1
fi
exit 0
HOOK_EOF
chmod +x /opt/secret-scan-hook.sh

install_secret_hook() {
  d="$1"
  if [ -d "$d/.git" ]; then
    cp /opt/secret-scan-hook.sh "$d/.git/hooks/pre-commit"
    chmod +x "$d/.git/hooks/pre-commit"
    echo "openab: installed secret-scan pre-commit hook in $d"
  fi
}
install_secret_hook "$REPO_AI_DIR"
install_secret_hook "$REPO_PLA_DIR"

mkdir -p "$REPO_AI_DIR/ai_wiki/raw" "$REPO_AI_DIR/_outputs/ai/inbox" "$REPO_AI_DIR/_outputs/misc/inbox" "$REPO_AI_DIR/_outputs/misc/raw"
[ -d "$REPO_PLA_DIR/.git" ] && mkdir -p "$REPO_PLA_DIR/wiki/raw" "$REPO_PLA_DIR/_outputs/pla/inbox"

chown -R node:node "$REPO_AI_DIR" 2>/dev/null || true
[ -d "$REPO_PLA_DIR" ] && chown -R node:node "$REPO_PLA_DIR" 2>/dev/null || true

[ -f "$REPO_AI_DIR/.zeabur/process_inbox.py" ] && cp "$REPO_AI_DIR/.zeabur/process_inbox.py" /opt/process_inbox.py
[ -f "$REPO_AI_DIR/.zeabur/CLAUDE.md" ] && cp "$REPO_AI_DIR/.zeabur/CLAUDE.md" /opt/CLAUDE.md
chmod +x /opt/process_inbox.py 2>/dev/null || true

if [ -f /opt/CLAUDE.md ]; then
  cp /opt/CLAUDE.md /home/node/CLAUDE.md
  cp /opt/CLAUDE.md "$REPO_AI_DIR/CLAUDE.md"
  [ -d "$REPO_PLA_DIR" ] && cp /opt/CLAUDE.md "$REPO_PLA_DIR/CLAUDE.md"
  chown node:node /home/node/CLAUDE.md 2>/dev/null || true
fi

cat > "$CONFIG_FILE" <<EOF
[discord]
bot_token = "$DISCORD_BOT_TOKEN"
allow_dm = true

[agent]
command = "claude-agent-acp"
args = []
working_dir = "/home/node"
inherit_env = ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"]
env = { REPO_DIR_AI = "$REPO_AI_DIR", REPO_DIR_PLA = "$REPO_PLA_DIR", GITHUB_TOKEN = "$GITHUB_TOKEN", GIT_USER_NAME = "$GIT_USER_NAME", GIT_USER_EMAIL = "$GIT_USER_EMAIL", GEMINI_API_KEY = "$GEMINI_API_KEY", HOME = "/home/node" }

[pool]
max_sessions = 10
session_ttl_hours = 6

[markdown]
tables = "code"
EOF

chown node:node "$CONFIG_FILE" 2>/dev/null || true
echo "openab: ready (Discord + Claude + claude-agent-acp)"

exec su -p -s /bin/sh node -c "exec openab run --config '$CONFIG_FILE'"
