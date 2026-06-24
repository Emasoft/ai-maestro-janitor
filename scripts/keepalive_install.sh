#!/usr/bin/env bash
# L0 OS-keepalive installer for the ai-maestro-janitor global daemon (TRDD-71ABD7V7).
#
# Writes the launchd LaunchAgent plist (macOS) or systemd user unit (Linux) that
# respawns the global daemon at boot / after a crash — the deepest immortality layer,
# the one that works even when ZERO Claude sessions are alive to fire a heartbeat.
#
# WHY this is a shipped, CPV-scanned shell file and NOT Python (the design keystone):
# the plist/unit body is written via an UNQUOTED heredoc so the shell expands $HOME at
# install time into the concrete absolute path launchd/systemd require. The launched
# program (ProgramArguments[0] / ExecStart) is the LITERAL
#   $HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py
# — the exact shape CPV's persistence discriminator (issue #152) folds to the in-tree,
# CPV-scanned, provably-inert entry, then C2/C3-scans. Because the discriminator can
# only resolve a plist that came from a heredoc in a SCANNED file (or a `cp SRC DST`),
# ALL persistence verbs (launchctl/systemctl) AND the heredoc MUST live together HERE,
# in one scanned file. The Python orchestrator (launchd_keepalive.py) carries NO
# persistence token — it only runs `bash keepalive_install.sh <cmd>` — so it never
# trips the discriminator with an unresolvable install line (the bug that got the old
# programmatic-plist launchd_keepalive.py extracted in v0.16.0/eb109fb).
#
# Nothing is generated or templated: the entry is a byte-identical verbatim copy of the
# shipped, scanned file (staged by keepalive_stage.py); this installer only writes a
# static OS config that points at the entry's FIXED path and asks the OS to load it.
set -eu

LABEL="com.ai-maestro-janitor.daemon"
# The janitor's FIXED persistent DATA dir (the same hard-coded location the arm skill
# and the memory subsystem use). NOT ${CLAUDE_PLUGIN_DATA}, which resolves to whichever
# plugin owns the current turn — wrong in a launchd/systemd-spawned, session-less process.
ENTRY="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py"
# The daemon pins its own log dir to the global-state dir (daemon.py setdefault); point
# launchd's stdout/stderr capture (resolution errors before logging starts) at the same.
LOG_DIR="$HOME/.claude/janitor-global-state"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/$LABEL.service"

detect_platform() {
  case "$(uname -s)" in
    Darwin) echo macos ;;
    Linux) echo linux ;;
    *) echo other ;;
  esac
}

install_macos() {
  mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
  # The redirect target below is the literal LaunchAgents plist path (not a shell var) so
  # CPV's heredoc-body extractor can locate this config body; the heredoc delimiter is
  # unquoted so the shell expands $HOME into the written file (launchd does not expand
  # variables itself). NOTE: keep this comment free of the heredoc-opener shape — a comment
  # carrying that shape would be mis-read as the opener and break resolution.
  cat > "$HOME/Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ai-maestro-janitor.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py</string>
    <string>--keepalive</string>
  </array>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG_DIR/daemon-keepalive.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/daemon-keepalive.err.log</string>
</dict>
</plist>
EOF
  # KEEPALIVE_SKIP_ACTIVATION writes the config but does NOT touch the OS service manager
  # — for a staged-but-not-activated install, a dry run, and side-effect-free tests.
  [ -n "${KEEPALIVE_SKIP_ACTIVATION:-}" ] && return 0
  uid="$(id -u)"
  # Clear any stale instance first so bootstrap never collides; both are best-effort —
  # a load failure must not abort the installer (the daemon's caller treats it best-effort).
  launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$PLIST" 2>/dev/null \
    || launchctl load -w "$PLIST" 2>/dev/null || true
}

install_linux() {
  mkdir -p "$UNIT_DIR" "$LOG_DIR"
  # Same shape as the plist branch: the redirect target below is the literal unit path so
  # CPV's extractor finds this config body; the unquoted delimiter lets the shell expand
  # $HOME into an absolute ExecStart (systemd does not expand variables itself). No injected
  # env is set here. As above, this comment stays free of the heredoc-opener shape.
  cat > "$UNIT_DIR/com.ai-maestro-janitor.daemon.service" <<EOF
[Unit]
Description=ai-maestro-janitor global daemon (OS keepalive)
After=default.target

[Service]
Type=simple
ExecStart=$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py --keepalive
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
EOF
  # See install_macos: write-config-only mode for staged installs / dry runs / tests.
  [ -n "${KEEPALIVE_SKIP_ACTIVATION:-}" ] && return 0
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now "$LABEL.service" 2>/dev/null || true
}

uninstall_macos() {
  uid="$(id -u)"
  launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
  launchctl unload -w "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
}

uninstall_linux() {
  systemctl --user disable --now "$LABEL.service" 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
}

# status: exit 0 iff the OS-keepalive artifact for this platform is on disk. Lets the
# Python orchestrator probe install-state without itself naming any persistence path
# (so launchd_keepalive.py stays free of the tokens that would trip the discriminator).
status_state() {
  case "$plat" in
    macos) [ -f "$PLIST" ] ;;
    linux) [ -f "$UNIT" ] ;;
    *) return 1 ;;
  esac
}

cmd="${1:-install}"
plat="$(detect_platform)"
case "$cmd" in
  install)
    case "$plat" in
      macos) install_macos ;;
      linux) install_linux ;;
      *) echo "keepalive: no OS keepalive for platform $plat" >&2; exit 0 ;;
    esac
    echo "keepalive: installed ($plat) → $ENTRY"
    ;;
  uninstall)
    case "$plat" in
      macos) uninstall_macos ;;
      linux) uninstall_linux ;;
      *) : ;;
    esac
    echo "keepalive: uninstalled ($plat)"
    ;;
  status)
    if status_state; then echo "keepalive: installed ($plat)"; exit 0;
    else echo "keepalive: not installed ($plat)"; exit 1; fi
    ;;
  *)
    echo "usage: keepalive_install.sh [install|uninstall|status]" >&2
    exit 2
    ;;
esac
