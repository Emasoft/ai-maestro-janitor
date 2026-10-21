"""Host-pressure detection and runaway-victim selection (TRDD-5G66S0HK).

The janitor already has a Tier-1 memory guard that kills SIX narrow
janitor-spawned shapes. What it does not have is the authority to kill a
runaway that CLAUDE CODE caused but the janitor did not spawn — which is
the whole of the 2026-10-20 incident (a 64 GB macOS box panicked under
swap exhaustion with 986 processes holding 19.8 GB).

This module supplies that authority, with two things the Tier-1 guard
deliberately never had: a pressure probe that can SEE the condition that
actually killed the machine, and an attribution rule that can tell an
agent's runaway from the user's own foreground work.

THE PRESSURE PROBE. Free memory alone is blind to the panic condition.
The 2026-10-20 panic log said "Compressor Info: 100% of segments limit
(BAD), 69 swapfiles" — so the probe reads SWAP USAGE, the SWAPFILE COUNT
and COMPRESSOR OCCUPANCY as well as free memory. A host that is
swap-exhausted with plenty of free RAM still reports CRITICAL.

Both of those named quantities are read DIRECTLY, not proxied (A-7, A-8):
the swapfile COUNT comes from enumerating the swapfile FILES on the VM
volume (macOS keeps them as ordinary files, and the directory is
world-readable), and the compressor's SEGMENT POOL comes from
`vm.compressor.segment.total` over `vm.compressor.segment.limit`. The
RAM-percentage reading of the compressor is kept only as a PROXY, for
hosts whose segment sysctls are unavailable — it is not the thing the
panic named.

THE ATTRIBUTION RULE — the part the card could not solve, settled by
MEASUREMENT on the owner's host (2026-10-20). The question was how to tell
an agent's runaway from a user's own dev server, a `vite` build, or a
`pytest` run the user started in their terminal. The answer is the
ENVIRONMENT SIGNAL, and it is exact:

    A process whose OWN environment carries CLAUDECODE, CLAUDE_PROJECT_DIR,
    CLAUDE_PLUGIN_DATA, CLAUDE_CODE_SESSION_ID or CLAUDE_CODE_CHILD_SESSION
    DESCENDS FROM A CLAUDE CODE SESSION.

Note what that proves, because the narrower claim is FALSE and this
header said so until a review caught it. The environment is INHERITED,
so the signal marks a DESCENDANT, not a direct spawn. A command the user
typed at a plain shell prompt inherits a shell environment with none of
the markers, so it is not attributed. But a terminal the user opened
FROM INSIDE a session — and everything they run in it — DOES carry them,
one generation further down. So "was started by an agent" is too strong
a claim, and the honest one is "descends from a session". The shape
allowlist, the age gate and the ABANDONMENT rule are what turn
relatedness into kill-worthiness, and the age gate alone is NOT enough:
a live `claude` session's own work must be protected by a signal that
says "abandoned", not merely by elapsed time.

The signal SURVIVES REPARENTING, which is why it and not ancestry alone is
the primary channel. Measured: `alcore serve` had ppid=1 (reparented to
launchd, its session long gone) yet still carried three of the
variables. Ancestry alone misses exactly that case — and an abandoned
watcher is by definition a reparented process.

Ancestry is kept as a SECOND, weaker signal, and it is necessary but not
sufficient on its own (the advisor's finding, TRDD-5G66S0HK): it cannot
see a reparented process at all, and a `claude` ANCESTOR proves the
process is a descendant of a session, which includes the user's own
work started inside that session.

ATTRIBUTION PROVES RELATEDNESS, NEVER KILL-WORTHINESS. A candidate must
also match a POSITIVE allowlist of runaway SHAPES, be older than the age
gate, not be a protected pid, and not be an interactive `claude` session.
Without the shape allowlist the rule degenerates to "biggest process
wins", which is what the janitor's Decision 1 refused.

THE ABANDONMENT SIGNAL — the SECOND, INDEPENDENT discriminator
(TRDD-ZIKYQQY0 A-1). Attribution says a process DESCENDS FROM a session;
abandonment says whether that session is STILL ALIVE. The rule is the
ancestry channel used as a NEGATIVE test:

    A candidate is ABANDONED iff its ancestor chain does NOT reach a
    live `claude` session process.

MEASURED on the live host (2026-10-20): the near-miss victim — a LIVE
`pytest` run in this very repo, 5675 s old, belonging to another session
— reaches pid 91163, a live `claude --continue`, through
29880 -> 29811 -> 29775 -> 91163. It is therefore NOT abandoned, and it
must not be a victim. The genuinely orphaned shapes on the same host
are ppid=1 with NO claude ancestor: their sessions are gone, so the
chain dead-ends. With this rule in place, the age gate is no longer the
ONLY thing protecting another session's running work — and the age gate
itself now has a FLOOR (`MIN_RUNAWAY_ETIME_S`), so no knob can remove
even that (A-0).
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import NamedTuple, Optional

# ---------- tunables -------------------------------------------------------

DEFAULT_MIN_FREE_MB = 1024
DEFAULT_SWAP_PCT = 95
DEFAULT_SWAPFILES = 32
DEFAULT_COMPRESSOR_PCT = 60

# THE BAR ON THE COMPRESSOR'S SEGMENT POOL — the quantity the 2026-10-20
# panic named ("100% of segments limit (BAD)"). MEASURED on this host
# (2026-10-20): 646714 / 1677721 = 38.5% on a HEALTHY host, stable
# across five samples three seconds apart, and the panic's condition
# was 100%.
#
# WHY 90: the healthy reading is 38.5%, so 90 is far above the host's
# normal operating point while still leaving room for the pool to grow
# under real pressure before the guard acts. It is deliberately NOT
# tight — a bar that a busy-but-healthy host crosses would put the
# janitor on the kill path for no reason, and the kill path is the
# expensive direction to be wrong in.
#
# The RAM-percentage proxy's bar (DEFAULT_COMPRESSOR_PCT = 60) is a
# DIFFERENT bar for a DIFFERENT quantity, and it is now only the
# fallback for hosts whose segment sysctls are unavailable.
DEFAULT_COMPRESSOR_SEGMENT_PCT = 90
DEFAULT_RUNAWAY_ETIME_S = 3600

# THE FLOOR of the runaway age gate (TRDD-ZIKYQQY0 A-0). The knob may be
# RAISED, never LOWERED: a caller that passes 0 (or anything under the
# floor) gets the floor. Without a floor the age gate was the ONLY thing
# standing between the live work of another session and the kill path,
# and a single mistyped 0 opened it completely.
MIN_RUNAWAY_ETIME_S = 900
DEFAULT_ALERT_RSS_KB = 4 * 1024 * 1024

# THE ENVIRONMENT VARIABLES THAT MARK A PROCESS AS AGENT-STARTED. Measured
# on the owner's host: the interactive `claude` sessions carry NONE of
# them, and the agent's children carry them whether or not they were
# reparented.
CLAUDE_ENV_MARKERS = (
    "CLAUDECODE",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    )

# THE POSITIVE OWNER POINTER (TRDD-ZIKYQQY0 A-1).
#
# CLAUDE_PID is a descendant->session pointer in the process ENVIRONMENT.
# MEASURED on the owner host: 48 processes carry it, the SET of owner pids is
# stable, and the COUNT of processes carrying one is NOT (68, 74, 94 across
# three reads minutes apart -- so the count is never a host property). It
# SURVIVES reparenting, which is exactly the case the ancestry channel
# cannot see at all.
#
# IT IS NOT IN CLAUDE_ENV_MARKERS, and it must NOT be added there: that
# tuple is a BOOLEAN marker test and this is a VALUE. A boolean test cannot
# read a pid, and a pid read as a boolean would be "is this string present",
# which is also true of the template artefact CLAUDE_PID={v}.
CLAUDE_PID_ENV = "CLAUDE_PID"

# THE CLAUDE-FAMILY EXECUTABLES -- the basenames that identify a process as
# part of the Claude family.
#
# claude and claude.exe are the CLI. Claude (CAPITAL C) is the macOS
# DESKTOP binary, MEASURED at /Applications/Claude.app/Contents/MacOS/Claude.
# The comparison is CASE-INSENSITIVE, so the capital-C spelling is covered by
# the lowercase entry; it is spelled out here anyway because the Desktop
# binary is a DIFFERENT PRODUCT and a reader must be able to see it.
#
# WHY CASE-INSENSITIVE MATTERS, MEASURED: the previous test was
# basename in ("claude", "claude.exe") -- lowercase only. A live Claude
# Desktop session descendants therefore had NO claude-named ancestor, and
# under the old NEGATED abandonment rule they read as ABANDONED. The case
# test was not a detail; it was a hole in the never-kill invariant.
CLAUDE_FAMILY_EXECUTABLES: tuple[str, ...] = (
    "claude",
    "claude.exe",
    "Claude",
)

# The comparison set, lowercased ONCE -- the family test is called per
# ancestor per row, and a set built per call would be a per-call allocation
# on the hot path.
_CLAUDE_FAMILY_LOWER = frozenset(name.lower() for name in CLAUDE_FAMILY_EXECUTABLES)

# THE POSITIVE ALLOWLIST OF RUNAWAY SHAPES. Attribution alone is not
# enough — without this the rule is "biggest process wins". Keep the list
# tight: every pattern here widens the kill surface.
#
# The first three are the janitor's OWN workload shapes. THEY ARE
# RE-TYPED LITERALS, not imported from memory_guard.JANITOR_WORKLOAD_
# SIGNATURES — `memory_guard` is not imported here, and a re-typed
# pattern can DRIFT from its original silently. (A previous version of
# this comment claimed they were reused rather than re-typed; that was
# FALSE, and `re.compile` caching made two independent tuples compare
# equal, which is what hid it.) If they are ever changed, BOTH files
# must change.
RUNAWAY_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclaude\s+plugin\s+marketplace\s+update\b"),
    re.compile(r"\bclaude\s+plugin\s+update\b"),
    re.compile(r"\bclaude\s+plugin\s+list\b"),
    re.compile(r"\bagentlenspro\s+statusline\b"),
    re.compile(r"\baimaestro-statusline-capture\.sh\b"),
    re.compile(r"\bpeak-space/watch\.mjs\b"),
    re.compile(r"\buv\s+run\s+pytest\b"),
    re.compile(r"(?:^|/)pytest\b"),

    # THE MEASURED REAL ORPHAN SHAPES (TRDD-ZIKYQQY0 A-1, item 15).
    #
    # These three are the ONLY long-lived, shape-matching, Claude-owned
    # processes measured on the owner host, and all four of their instances
    # belonged to the ONE dead owner (20716). MEASURED command lines:
    #
    #   node /Users/User/ai-maestro/node_modules/.bin/tsx server.mjs
    #   <homebrew node 22>/bin/node --require \
    #       /Users/User/ai-maestro/node_modules/tsx/dist/preflight.cjs \
    #       --import file:///Users/User/ai-maestro/node_modules/tsx/dist/lo...
    #   /Users/User/ai-maestro/node_modules/@esbuild/darwin-arm64/bin/esbuild \
    #       --service=0.27.2 --ping
    #
    # WHY THE PATTERNS ARE THIS TIGHT, and why that matters. A generic
    # `node` pattern would match EVERY foreign client built on node -- and
    # `gemini` (Google CLI) is exactly that: MEASURED running as pid 65811
    # with RSS 152 MB carrying CLAUDE_PID=20716 (the DEAD owner) plus
    # CLAUDE_CODE_CHILD_SESSION=1. A generic `node` pattern would have
    # matched it. So each pattern below names the SPECIFIC artefact that
    # identifies the shape:
    #
    #   * `tsx server.mjs` -- the server entrypoint, not any tsx invocation;
    #   * `node --require .../tsx/dist/preflight.cjs` -- the tsx PREFLIGHT
    #     hook, which is what the node --require orphan actually is;
    #   * `esbuild --service` -- the esbuild SERVICE daemon flag.
    #
    # A WIDENED SHAPE LIST IS WHAT MAKES THE POLARITY FIX OBSERVABLE. The
    # advisor measured that with the narrow list the kill path selects ZERO
    # processes on this host, because the only shape-matching population is
    # TRANSIENT statusline captures aged 0-10 s -- the age gate, not the
    # polarity, was what made the guard inert. A fix that produces no
    # observable change in the killable count is what a WRONG fix looks
    # like, so the shapes the real orphans actually have are here.
    #
    # THE SAFETY CONSEQUENCE IS EXPLICIT: a widened list means a foreign
    # client launched from a Claude shell can now reach the kill path, so
    # the forbidden-client list (see `_FORBIDDEN_EXECUTABLES`, which now
    # carries `gemini`) is LOAD-BEARING, not decorative.
    re.compile(r"\btsx\s+server\.mjs\b"),
    re.compile(r"\bnode\b.*--require\b.*[/\\]tsx[/\\]dist[/\\]preflight\.cjs\b"),
    re.compile(r"\besbuild\s+--service\b"),
)


# The owner's other AI clients. EXPLICITLY FORBIDDEN by the owner
# directive of 2026-10-20: "do not touch processes executed by other ai
# clients like codex or copilot".
#
# EACH PATTERN MATCHES THE EXECUTABLE (argv[0]'s basename) OR A PATH
# SEGMENT, not a bare substring anywhere on the command line. The
# distinction is load-bearing and the first version got it wrong in
# BOTH directions:
#
#   * `\b aider\b` (with a LEADING SPACE inside the word boundary) never
#     matched the executable form `aider --model x` — it only matched
#     `aider` mid-string — so aider was NOT protected at all. MEASURED:
#     'aider --model x' -> not forbidden; 'x aider y' -> forbidden.
#   * A bare `\bcodex\b` matches a FILENAME too, so
#     `pytest tests/test_codex_pagination.py` was refused as a "forbidden
#     client". Over-refusing is the safe direction for a kill, but it
#     makes the rule wrong, and a rule that is wrong for the wrong reason
#     is a rule that will be "fixed" into being wrong the other way.
#
# So the patterns below anchor on an EXECUTABLE POSITION: the start of
# the command, or a path segment boundary.
_FORBIDDEN_EXECUTABLES: tuple[str, ...] = (
    "codex",
    "codex-app-server",
    "copilot",
    "copilot-agent",
    "aider",
    "cursor",
    "cursor-agent",
    "lm-studio",
    "lmstudio",
    # `late` is a DIFFERENT AI client from the claude family, and it was
    # MEASURED running on this host (two `late --continue-project`
    # processes, 2026-10-20). The owner directive names the CLASS of other
    # AI clients, so this list is a LOWER BOUND on the set the owner
    # forbade, NOT a closed set.
    #
    # AND IT IS NOT THE ONLY DEFENCE -- the earlier comment here said
    # "the ONLY protection", which was FALSE and contradicted the very
    # next sentence. The age gate, the shape allowlist, the ownership gate
    # and the owner-liveness test ALSO refuse. This list is DEFENCE IN
    # DEPTH: the last line of a layered refusal, not the only line.
    #
    # WHY A MISSING ENTRY IS A SAFETY BUG once the shape list widens
    # (TRDD-ZIKYQQY0 A-1, item 8). The shape allowlist now carries the
    # MEASURED real orphan shapes, including `node`-based ones. `gemini`
    # (Google CLI) is a node program, so it is exactly the kind of process
    # a widened node pattern can match. MEASURED: `gemini` ran on this
    # host as pid 65811 with RSS 152 MB carrying `CLAUDE_PID=20716` -- the
    # DEAD owner -- plus CLAUDE_CODE_CHILD_SESSION=1 and
    # CLAUDE_CODE_ENTRYPOINT=cli. It was NOT in this list, and it is not
    # running now; that is irrelevant to the correctness of the rule,
    # because the rule must be right for the population that APPEARS.
    # Without a name entry, a foreign client under a dead Claude owner is
    # KILLABLE, and the owner directive forbids exactly that.
    "late",
    # `gemini` is the Google CLI. MEASURED running on this host under the
    # DEAD owner 20716 (see the comment above). Its launcher is a node
    # script: /opt/homebrew/bin/gemini -> gemini-cli/0.46.0/bin/gemini.
    "gemini",
)


def is_forbidden_client(command: str) -> bool:
    """True iff the command's EXECUTABLE is another AI client.

    Matches the BASENAME of any word, or a path SEGMENT anywhere in the
    command — so `/usr/local/bin/codex`, `node .../codex/bin/codex.js`
    and `npx codex` are all caught, because a forbidden client's NAME
    appears as a word or as a path component wherever the user put it.

    NOT a bare substring inside a longer word: `test_codex.py` is a
    filename, not a client.

    "lm studio" is matched too, because the product is spelled both ways
    and a forbidden client must not be reachable by a different spelling.
    """
    if not command:
        return False
    words = command.split()
    for word in words:
        base = os.path.basename(word).lower()
        if base in _FORBIDDEN_EXECUTABLES:
            return True
        # A PATH SEGMENT: /opt/homebrew/bin/codex, .../codex/bin/codex.js.
        #
        # A SEGMENT IS A SEGMENT — a word that CONTAINS a slash. A
        # BARE word is not a path segment, and treating it as one made
        # `npx codex` match here as well as in the launcher check below,
        # which is why the launcher check looked redundant and why its
        # mutation survived. The distinction matters for the OTHER
        # direction too: `pytest tests/test_codex_pagination.py` has a
        # segment `test_codex_pagination.py`, which is not the name, so
        # it is not refused.
        if "/" in word:
            for segment in word.lower().split("/"):
                if segment in _FORBIDDEN_EXECUTABLES:
                    return True
        if segment_has_lm_studio(word):
            return True
    return False


def segment_has_lm_studio(word: str) -> bool:
    """True for `lm-studio`, `lm_studio` and `lm studio`."""
    lowered = word.lower()
    return "lm-studio" in lowered or "lm_studio" in lowered or "lm studio" in lowered

# THE JANITOR'S OWN INSTALLATION — the paths a janitor-owned process
# runs from, and the launchd label its keepalive is installed under.
# The launchd label is the one the install script writes
# (`scripts/keepalive_install.sh`), and it is in the process's command
# line only when launchd started the job, so it is a second, independent
# handle on the same exclusion.
JANITOR_LAUNCHD_LABEL = "com.ai-maestro-janitor.daemon"

# THE PLUGIN'S OWN ROOT, resolved the way the daemon resolves it: the
# guard lives at `<plugin-root>/scripts/lib/runaway_guard.py`, so the
# root is two levels up from the library directory. Resolved ONCE, at
# import, because a probe that re-resolves per row would stat the
# filesystem for every process on the host.
JANITOR_ROOT = Path(__file__).resolve().parent.parent.parent


def janitor_own_paths() -> tuple[Path, ...]:
    """The directories a janitor-owned process runs FROM.

    Two of them, and both are needed:

      * the PLUGIN ROOT — the installed plugin tree
        (`~/.claude/plugins/cache/<mkt>/ai-maestro-janitor/<ver>/`);
        the daemon, the keepalive entry, the rotator and every detector
        run from inside it;
      * the PLUGIN DATA DIR — the machine-wide state
        (`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`);
        the keepalive entry and the rotator are launched from there.

    The DATA dir is read from the environment when it is set, because
    that is how the janitor finds it at runtime, and it falls back to
    the standard location under the Claude config dir.
    """
    paths = [JANITOR_ROOT]
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data_dir:
        paths.append(Path(data_dir))
    else:
        cfg = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
        paths.append(Path(cfg) / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins")
    return tuple(p for p in paths if p and str(p) not in ("", "."))


def is_janitor_own(command: str) -> bool:
    """True iff this command line runs FROM the janitor's own installation.

    A-6 (TRDD-ZIKYQQY0): the janitor's launchd agent was safe only
    because its command line happened to match no runaway shape TODAY.
    That is an accident, not an invariant: the shape allowlist already
    contains `pytest` and `uv run pytest`, so a future allowlist entry
    could match the janitor itself — and then the janitor would kill
    its own daemon.

    So the exclusion is STRUCTURAL: any process whose command line
    points into the plugin's own tree, into the plugin's own data
    dir, or that carries the janitor's launchd label is the janitor's
    own, whatever its command line looks like.

    The label check is separate from the path checks because a
    launchd-started job's command line carries the label only
    sometimes, while its path always points into the installation.
    """
    if not command:
        return False
    if JANITOR_LAUNCHD_LABEL in command:
        return True
    for own in janitor_own_paths():
        own_str = str(own)
        if own_str and own_str in command:
            return True
    return False

# An interactive `claude` session — the thing the user is typing into.
# NEVER killable, even when it is the largest process on the host.
_CLAUDE_ANYTHING = re.compile(r"(?:^|/|\s)claude(?:\s|$)")


class ProcRow(NamedTuple):
    """One parsed `ps -axo pid,ppid,rss,etime,command` row."""

    pid: int
    ppid: int
    rss_kb: int
    etime_s: int
    command: str


class Pressure(NamedTuple):
    """The host's pressure state, with the readings that produced it."""

    state: str            # "healthy" | "elevated" | "critical"
    free_mb: Optional[int]
    swap_used_mb: Optional[int]
    swap_total_mb: Optional[int]
    swap_pct: Optional[int]
    swapfiles: Optional[int]
    compressor_pct: Optional[int]
    # The compressor's SEGMENT POOL as a percentage of its limit — the
    # quantity the 2026-10-20 panic actually named ("100% of segments
    # limit"). `compressor_pct` above is the RAM PERCENTAGE PROXY. Both
    # are reported, and the segment pool is the one that ARMS the kill
    # path. Defaults to None so a caller that does not know about it
    # still constructs a Pressure.
    compressor_segment_pct: Optional[int] = None

    def readings(self) -> str:
        """A one-line, human-readable rendering of the readings."""
        def part(value: Optional[int], unit: str) -> str:
            return "?" if value is None else f"{value}{unit}"
        return (
            f"free {part(self.free_mb, 'MB')}, "
            f"swap {part(self.swap_used_mb, 'MB')}"
            + (f"/{part(self.swap_total_mb, 'MB')}" if self.swap_total_mb else "")
            + (f" ({part(self.swap_pct, '%')})" if self.swap_pct is not None else "")
            + ", "
            f"swapfiles {part(self.swapfiles, '')}, "
            f"compressor {part(self.compressor_pct, '%')}"
            + (
                f" (segments {part(self.compressor_segment_pct, '%')})"
                if self.compressor_segment_pct is not None
                else ""
            )
        )


# ---------- pure parsers ----------------------------------------------------

def parse_etime(raw: str) -> int:
    """Parse ps ELAPSED ([[dd-]hh:]mm:ss) into seconds. Unparseable -> 0.

    0 is the SAFE direction: an unparseable age fails the runaway-age gate,
    so the row can never be killed on a parsing accident.
    """
    raw = raw.strip()
    m = re.fullmatch(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)", raw)
    if not m:
        return 0
    days, hours, minutes, seconds = m.groups()
    total = int(minutes) * 60 + int(seconds)
    if hours is not None:
        total += int(hours) * 3600
    if days is not None:
        total += int(days) * 86400
    return total


def parse_ps_snapshot(text: str) -> list[ProcRow]:
    """Parse `ps -axo pid,ppid,rss,etime,command` output (header tolerated).

    Malformed lines are skipped — the guard prefers missing a row to
    misattributing one.
    """
    rows: list[ProcRow] = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid_s, ppid_s, rss_s, etime_s_raw, command = parts
        if not (pid_s.isdigit() and ppid_s.isdigit() and rss_s.isdigit()):
            continue
        rows.append(ProcRow(
            pid=int(pid_s), ppid=int(ppid_s), rss_kb=int(rss_s),
            etime_s=parse_etime(etime_s_raw), command=command.strip(),
        ))
    return rows


def parse_swapusage(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(used_mb, total_mb, swapfile_count) from `sysctl -n vm.swapusage`.

    MEASURED FORMAT on this host:
        total = 8192.00M  used = 6715.00M  free = 1477.00M  (encrypted)

    The TOTAL is read as well as the used figure, and it is the total
    that makes the ratio meaningful. See `swap_ratio_pct`.

    The swapfile COUNT is not in vm.swapusage on any macOS this was
    measured on, and `vm.swapinfo` does not exist on macOS at all
    ('sysctl: unknown oid vm.swapinfo'), so this parser never finds a
    count on macOS. It is still LOOKED FOR on hosts that do report it.

    ON macOS THE COUNT IS READ A DIFFERENT WAY — by enumerating the
    swapfile FILES on the VM volume. See `count_swapfiles`, and see
    `read_swap` for how the two are combined. The count was the signal
    the 2026-10-20 panic named ('69 swapfiles'), and it IS readable
    here; the sysctl route simply is not the route.
    """
    def _mb(field: str) -> Optional[int]:
        m = re.search(field + r"\s*=\s*([\d.]+)\s*([MG])", text)
        if not m:
            return None
        value = float(m.group(1))
        return int(value) if m.group(2) == "M" else int(value * 1024)

    used_mb = _mb("used")
    total_mb = _mb("total")
    count = re.search(r"(\d+)\s+files", text)
    files: Optional[int] = int(count.group(1)) if count else None
    return used_mb, total_mb, files


def swap_ratio_pct(used_mb: Optional[int], total_mb: Optional[int]) -> Optional[int]:
    """Swap usage as a PERCENTAGE of the swapfile's own total.

    WHY A RATIO AND NOT AN ABSOLUTE FIGURE — MEASURED, and this is the
    calibration that decided the thresholds. macOS preallocates and KEEPS
    a swapfile full once it has grown, so a host that used swap once
    keeps it used. On the owner's host the swapfile is 8192 MB with
    6715 MB used — 82% of the file — and that figure was STABLE across
    a minute of sampling on a day the host was entirely healthy (free
    memory 22104 MB, compressor ~1% of physical RAM).

    So an absolute "swap used" bar of 2048 MB is crossed by this host's
    NORMAL operating point, and a guard armed with it would be
    permanently critical and would kill a process every minute. The
    ratio has the same problem on this host (82% used is not pressure),
    which is why the ratio alone is not sufficient either — but it is
    the honest unit, because it measures how much of the FILE is
    consumed rather than how much memory has ever been paged, and on a
    host whose swapfile has grown to 64 GB the ratio is the only
    figure that scales.

    None when either figure is unknown. A ratio of a total of zero is
    None too, never 0: "no swapfile" is not "no swap pressure".
    """
    if used_mb is None or total_mb is None or total_mb <= 0:
        return None
    return int(used_mb * 100 / total_mb)


def parse_compressor_pct(text: str, total_mb: int, page_size: int) -> Optional[int]:
    """Compressor occupancy as a PERCENTAGE of physical memory.

    MEASURED on this host: `Pages occupied by compressor: 1869016` with a
    16384-byte page size and 65536 MB of RAM is ~46% — a real reading, not
    a guess. `Pages stored in compressor` is the COMPRESSED size and is a
    different number; the OCCUPIED pages are the ones that cost physical
    memory, so that is the one measured.

    None when the line is absent or the arithmetic is impossible — never
    guess, because a wrong number here flips a healthy host to critical.
    """
    m = re.search(r"Pages occupied by compressor:\s*(\d+)", text)
    if not m or total_mb <= 0 or page_size <= 0:
        return None
    occupied_mb = (int(m.group(1)) * page_size) / (1024 * 1024)
    return int(occupied_mb * 100 / total_mb)


# ---------- the pressure probe ---------------------------------------------

# THE COMPRESSOR SEGMENT-POOL BAR'S PLUGIN OPTION (TRDD-ZIKYQQY0 A-1, item 13).
#
# EVERY OTHER BAR IS CONFIGURABLE, and this one was not: the daemon read
# `CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_MIN_FREE_MB`, `..._SWAP_PCT`,
# `..._SWAPFILES` and `..._COMPRESSOR_PCT` from the plugin options and
# passed them in, but the SEGMENT bar was left at its in-code default of
# 90 with no way to change it. The bar was in effect; only its
# configurability was missing.
#
# IT IS READ HERE, IN THE GUARD, rather than in the daemon, and the reason
# is a CONCURRENCY constraint: `scripts/daemon.py` was owned by another
# worker while this was written, so the daemon's call site could not be
# touched. Reading the option in the guard makes the bar configurable
# without that edit -- the daemon's call still passes nothing, and the
# guard's own reading of the option supplies the bar.
#
# `state.plugin_option` is the same reader the daemon uses, and it honours
# a real environment variable first and the settings.json mirror second.
COMPRESSOR_SEGMENT_PCT_ENV = "CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_COMPRESSOR_SEGMENT_PCT"


def compressor_segment_pct_bar(default: int = DEFAULT_COMPRESSOR_SEGMENT_PCT) -> int:
    """The segment-pool bar, from the plugin option, or the default.

    A malformed value falls back to the default rather than to zero: a
    zero bar would arm the kill path on a host whose segment pool is
    merely LARGE, which is the wrong direction for a knob.
    """
    try:
        import state as _state  # noqa: PLC0415 - sibling lib, lazily imported
    except ImportError:
        return default
    raw = _state.plugin_option(COMPRESSOR_SEGMENT_PCT_ENV)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (AttributeError, ValueError):
        return default
    return value if value > 0 else default
def host_pressure(
    *,
    min_free_mb: int = DEFAULT_MIN_FREE_MB,
    swap_pct_bar: int = DEFAULT_SWAP_PCT,
    swapfiles: int = DEFAULT_SWAPFILES,
    compressor_pct: int = DEFAULT_COMPRESSOR_PCT,
    compressor_segment_pct: Optional[int] = None,
) -> Pressure:
    """Read the host's pressure state. Every probe failure degrades to None.

    THE STATE IS A DISJUNCTION OVER THE KNOWN-BAD READINGS, and this is
    the load-bearing correction. The first version required the free
    memory to be bad BEFORE it would call the host critical:

        if free_bad and (swap_bad or files_bad or comp_bad):

    which meant a swap-exhausted host with healthy free memory read as
    merely `elevated` — and the kill path NEVER ARMED in exactly the
    scenario the feature was built for. MEASURED on the 2026-10-20
    panic's shape: free 30000 MB, swap 8192 MB, 64 swapfiles, compressor
    90% gave `elevated`, not `critical`. The panic log named the
    condition itself ('Compressor Info: 100% of segments limit (BAD), 69
    swapfiles'), and the `and` re-introduced the very blind spot the
    probe was extended to remove.

    The `and` was also backwards in the OTHER direction: on a host under
    memory pressure `vm_stat` is the call most likely to be slow or to
    fail, so a FAILED free-memory read meant a swap-exhausted host read
    as `elevated` and the guard stood down on a dying machine.

    So: `critical` when ANY known reading is past its bar. Free memory
    is one arm of the disjunction, not the gate on all of them.

    An UNKNOWN reading still never pushes the state up: a reading that
    could not be taken is not a reading that is bad, and "critical" arms
    the kill path. Never kill on missing data.
    """
    free_mb = free_memory_mb()
    swap_used, swap_total, files = read_swap()
    compressor = read_compressor_pct()
    # THE SEGMENT POOL — the quantity the 2026-10-20 panic named
    # ("100% of segments limit"). It is a direct reading, so it is the
    # compressor arm's PRIMARY signal. The RAM-percentage proxy is kept
    # as the fallback for hosts where the segment sysctls are absent.
    compressor_segments = read_compressor_segment_pct()

    # THE SEGMENT BAR, resolved. A caller that passes one explicitly wins
    # (that is how the daemon's own knob used to work); a caller that
    # passes none gets the CONFIGURED bar, read from the plugin option --
    # so the bar is configurable on the same footing as every other one
    # (TRDD-ZIKYQQY0 A-1, item 13).
    segment_bar = (
        compressor_segment_pct
        if compressor_segment_pct is not None
        else compressor_segment_pct_bar()
    )

    free_bad = free_mb is not None and free_mb < min_free_mb
    # The swap bar is a RATIO of the swapfile's own total, not an
    # absolute number of megabytes. MEASURED on the owner's host: the
    # swapfile is 8192 MB with 6715 MB used — 82% — and that was STABLE
    # across a minute of sampling on a day the host was entirely
    # healthy, because macOS keeps a swapfile full once it has grown.
    # An absolute bar is therefore crossed by this host's NORMAL
    # operating point, which would leave the guard permanently critical.
    swap_pct = swap_ratio_pct(swap_used, swap_total)
    swap_bad = swap_pct is not None and swap_pct >= swap_pct_bar
    files_bad = files is not None and files >= swapfiles
    # THE COMPRESSOR ARM IS THE SEGMENT POOL — the thing the panic named
    # — with the RAM-percentage proxy as the fallback for a host whose
    # segment sysctls are unavailable. Note the fallback direction: the
    # proxy arms the arm when the real quantity is UNKNOWN, which is
    # correct, because "the reading I could take is bad" is a fact
    # while "the reading I could not take is fine" is not.
    comp_bad = (
        compressor_segments is not None
        and compressor_segments >= segment_bar
    ) or (
        compressor_segments is None
        and compressor is not None
        and compressor >= compressor_pct
    )

    exhausted = swap_bad or files_bad or comp_bad

    # THREE STATES, and the middle one is reachable. The first version
    # had only two — `critical` or `healthy` — and the daemon's "the
    # host is trending toward the panic" branch was then DEAD CODE,
    # because a branch that can never run is a branch whose comment
    # lies about what the owner will see.
    #
    # `elevated` is the WARNING tier: a reading is over half its
    # critical bar. It is the early warning that makes a rising trend
    # visible before the host is in trouble, and it is what the daemon
    # logs when the kill path does NOT arm.
    #
    # `critical` is any reading over its FULL bar — one signal past its
    # bar is enough, because the 2026-10-20 panic named one signal
    # ('100% of segments limit', '69 swapfiles') and a conjunction
    # re-introduced the blind spot the probe was extended to remove.
    free_warn = free_mb is not None and free_mb < min_free_mb * 2
    swap_warn = swap_pct is not None and swap_pct >= swap_pct_bar // 2
    files_warn = files is not None and files >= swapfiles // 2
    comp_warn = (
        compressor_segments is not None
        and compressor_segments >= segment_bar // 2
    ) or (
        compressor_segments is None
        and compressor is not None
        and compressor >= compressor_pct // 2
    )
    if exhausted or free_bad:
        state = "critical"
    elif free_warn or swap_warn or files_warn or comp_warn:
        state = "elevated"
    else:
        state = "healthy"
    return Pressure(
        state, free_mb, swap_used, swap_total, swap_pct, files, compressor,
        compressor_segments,
    )


def free_memory_mb() -> Optional[int]:
    """Free MB on macOS. None = unknown (never guess)."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["vm_stat"], capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode != 0:
            return None
        page = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "hw.pagesize"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        page_size = int(page.stdout.strip()) if page.returncode == 0 else 16384
        free = re.search(r"Pages free:\s*(\d+)", out.stdout)
        spec = re.search(r"Pages speculative:\s*(\d+)", out.stdout)
        if not free:
            return None
        pages = int(free.group(1)) + (int(spec.group(1)) if spec else 0)
        return int(pages * page_size / (1024 * 1024))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def read_swap() -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(used_mb, total_mb, swapfile_count). Any may be None = unknown.

    THE SWAPFILE COUNT IS READABLE ON macOS — not through a sysctl, but
    by ENUMERATING THE SWAPFILE FILES on the VM volume. MEASURED on
    this host as an unprivileged user (uid 501): the directory is
    `drwxr-xr-x root wheel` and holds 7 files named swapfile0..4, 6,
    7 — NOTE THE GAP AT 5, so the count must be by FILE, never by
    name index. Each file is exactly 1073741824 bytes, matching
    `vm.compressor.swapper.swapfile_size_max`.

    THE CROSS-CHECK, which is what makes the count trustworthy: 7
    files x 1 GiB = 7168 MB, and `sysctl -n vm.swapusage` reports
    total = 7168.00M. EXACT MATCH.

    AND THE CROSS-CHECK IS NOW WIRED IN, not merely available. The
    per-file size and the swap total are both read here, and if the
    counted files do not account for the reported total then the COUNT
    is not a count: a count that disagrees with the total means one of
    the two readings is wrong, and the guard must not act on a reading
    it cannot trust. In that case the count becomes None -- UNKNOWN --
    which is the same direction as every other failed probe here.

    MEASURED on the owner host (2026-10-21): 5 swapfile files of
    1073741824 bytes each = 5120 MB, and `vm.swapusage` reports
    total = 5120.00M. EXACT MATCH, so the count survives the
    cross-check here.

    `vm.swapinfo` is still attempted first, as the source for hosts
    that report it that way; when it is absent (as it is on macOS —
    'sysctl: unknown oid vm.swapinfo') the file listing is the
    fallback. A failure of BOTH is None = unknown, like every other
    probe: never guess, because a wrong count here flips a healthy
    host to critical.
    """
    used: Optional[int] = None
    total: Optional[int] = None
    files: Optional[int] = None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["sysctl", "-n", "vm.swapusage"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode == 0:
            used, total, files = parse_swapusage(out.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        out = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "vm.swapinfo"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode == 0:
            _, _, info_files = parse_swapusage(out.stdout)
            if info_files is not None:
                files = info_files
    except (OSError, subprocess.SubprocessError):
        pass
    if files is None:
        files = count_swapfiles()
    # THE CROSS-CHECK, WIRED. A count that does not account for the
    # reported swap total is not a count, so it is discarded as UNKNOWN
    # rather than reported as a number the guard would act on.
    if files is not None and total is not None:
        per_file = swapfile_size_bytes()
        if swapfile_total_matches_count(files, per_file, total) is False:
            files = None
    return used, total, files


def _sysctl_int(name: str) -> Optional[int]:
    """One `sysctl -n <name>` reading as an int, or None = unknown."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["sysctl", "-n", name],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


def read_compressor_segment_pct() -> Optional[int]:
    """The compressor's SEGMENT POOL as a percentage of its limit, or None.

    THIS IS THE QUANTITY THE 2026-10-20 PANIC NAMED. The panic log read
    "Compressor Info: 32% of compressed pages limit (OK) and 100% of
    segments limit (BAD) with 69 swapfiles" — the segments limit is the
    compressor's OWN pool exhausted, and it is a direct sysctl reading:

        vm.compressor.segment.total  /  vm.compressor.segment.limit

    MEASURED on this host (2026-10-20): 646714 / 1677721 = 38.6% on a
    HEALTHY host, stable across five samples three seconds apart. The
    panic's condition was 100%.

    It is NOT the same quantity as `read_compressor_pct` (which is a
    PROXY — see that function's docstring). This is the thing itself.
    """
    total = _sysctl_int("vm.compressor.segment.total")
    limit = _sysctl_int("vm.compressor.segment.limit")
    if total is None or limit is None or limit <= 0:
        return None
    return int(total * 100 / limit)
def read_compressor_pct() -> Optional[int]:
    """Compressor occupancy as a percent of physical memory, or None.

    THIS IS A PROXY, NOT THE THING. It measures "Pages occupied by
    compressor" as a percentage of PHYSICAL RAM. The condition the
    2026-10-20 panic actually named was "100% of segments limit" — the
    compressor's own SEGMENT POOL exhausted — which is a DIFFERENT
    quantity. The two correlate (a fuller segment pool means more
    compressed pages resident), but a percentage of RAM is not a
    percentage of a segment limit, and this docstring used to present
    the proxy as though the proxy question were settled.

    The real quantity is one sysctl away and IS read, by
    `read_compressor_segment_pct`, which now drives the compressor arm
    of `host_pressure`. The proxy is kept as a SECONDARY reading: it is
    still reported, and it still arms the kill path on a host where the
    segment sysctls are unavailable — where the real quantity is
    UNKNOWN, not "fine".

    MEASURED on this host: `Pages occupied by compressor: 87246` with a
    16384-byte page size and 65536 MB of RAM is ~2% — well under any
    sane bar. `Pages stored in compressor` is the COMPRESSED size and is
    a different number; the OCCUPIED pages are the ones that cost
    physical memory, so that is the one measured.
    """
    try:
        out = subprocess.run(  # noqa: S603
            ["vm_stat"], capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode != 0:
            return None
        total = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if total.returncode != 0:
            return None
        total_mb = int(total.stdout.strip()) // (1024 * 1024)
        page = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "hw.pagesize"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        page_size = int(page.stdout.strip()) if page.returncode == 0 else 16384
        return parse_compressor_pct(out.stdout, total_mb, page_size)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


# ---------- attribution ----------------------------------------------------

# THE `claude` PLUGIN-SUBCOMMAND FORMS — the ONLY `claude` invocations that
# are NOT an interactive session. They are stated HERE, explicitly, rather
# than read as a positional slice of RUNAWAY_SHAPES.
#
# WHY NOT A SLICE: the interactive-session check is the rule that stands
# between the user and the killing of the session they are typing into, and
# a positional slice makes that rule depend on the ORDER OF A LITERAL. A
# future edit that inserts a pattern before index 3 would silently change
# what "interactive" means, with no comment saying the order mattered and
# no test able to see it. MEASURED as a surviving mutation: changing
# `RUNAWAY_SHAPES[:3]` to `RUNAWAY_SHAPES[:1]` left the whole suite green.
# The rule must not be able to change by accident, so it names its own
# patterns.
CLAUDE_PLUGIN_SUBCOMMAND = re.compile(
    r"\bclaude\s+plugin\s+(?:marketplace\s+update|update|list)\b"
)


def is_interactive_claude(command: str) -> bool:
    """True iff this command line is an interactive `claude` session.

    NEVER killable. The user is typing into it; killing it is the single
    most likely harm of the whole feature.

    THE TEST IS A NEGATIVE: a command that mentions `claude` and is NOT
    one of the explicit plugin subcommand forms is an interactive session.
    The plugin subcommands are the ONLY exception, and they are named
    here rather than sliced out of the runaway-shape allowlist — see
    `CLAUDE_PLUGIN_SUBCOMMAND` for why.

    Note what this does and does not claim. A `claude` command with the
    plugin subcommand is a janitor workload; anything else that mentions
    `claude` is treated as the user's session. That is deliberately
    conservative: an unrecognised `claude` invocation is spared rather
    than killed.
    """
    if not _CLAUDE_ANYTHING.search(command):
        return False
    return not CLAUDE_PLUGIN_SUBCOMMAND.search(command)

def snapshot_claude_env() -> dict[int, tuple[bool, Optional[int]]]:
    """{pid: (carries a Claude marker, parsed CLAUDE_PID owner)} for the host.

    ONE `ps eww -axo pid=,command=` read for the WHOLE host, instead of one
    read per process.

    WHY IT EXISTS, and it is a COST fact, not a preference. The ownership
    clause is the THIRD clause of the kill path, so it is evaluated for
    every candidate row. MEASURED on the owner host: `ps eww -o command=
    -p <pid>` costs ~25 ms per call, so a per-row read over the host's
    ~1000 processes is ~25 SECONDS of subprocess spawn per guard beat --
    and the guard beat runs every 60 seconds. The batched read of the same
    information measures 0.8 s.

    THE PARSE IS THE SAME ONE `read_claude_env_once` does, applied to each
    line: only a `NAME=value` TOKEN counts, because `ps eww` returns the
    ARGV and the ENVIRONMENT concatenated with no separator, so a bare
    `CLAUDECODE` in a command line is not an environment variable.
    MEASURED: this host's own `ps eww` output contains the token
    `"CLAUDECODE\\|CLAUDE_PROJECT_DIR"`, and that token came from the
    COMMAND LINE of a `grep`, not from any environment.

    A pid that is absent from the map is absent from the RESULT too -- the
    map is the truth about the processes the read saw, and a pid it does
    not hold is one whose environment could not be read. That is UNKNOWN,
    never "not Claude-owned by a dead owner".
    """
    envs: dict[int, tuple[bool, Optional[int]]] = {}
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ps", "eww", "-axo", "pid=,command="],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return envs
    if out.returncode != 0:
        return envs
    for line in out.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        pid_text, rest = parts
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        marker = False
        owner: Optional[int] = None
        for token in rest.split():
            name, sep, value = token.partition("=")
            if not sep:
                continue
            if name in CLAUDE_ENV_MARKERS:
                marker = True
            elif name == CLAUDE_PID_ENV and owner is None:
                owner = parse_claude_pid_value(value, own_pid=pid)
        envs[pid] = (marker, owner)
    return envs


# THE BATCHED SNAPSHOT'S FRESHNESS WINDOW. The guard beat runs every 60 s
# and a snapshot read costs 0.8 s, so a window comfortably under the beat
# keeps the read count at one per beat while still letting a process that
# started seconds ago be seen (a pid the snapshot does not hold falls back
# to a direct read -- see `read_claude_env_once`).
_ENV_SNAPSHOT_TTL_S = 30.0
_env_snapshot_cache: dict[int, tuple[bool, Optional[int]]] = {}
_env_snapshot_at: float = 0.0


def cached_claude_env() -> dict[int, tuple[bool, Optional[int]]]:
    """The batched env snapshot, refreshed at most every
    `_ENV_SNAPSHOT_TTL_S` seconds.

    THE CACHE IS WHAT MAKES THE REORDERED OWNERSHIP CLAUSE AFFORDABLE.
    Without it, the third clause of the kill path would spawn one `ps`
    per row per beat -- MEASURED ~25 s for the owner host's ~1000
    processes, against a 60 s beat.

    The cache is a CACHE of a READING, not a memo of a decision: it
    holds the same facts a fresh read would, and the TTL is short
    relative to the beat. A caller that wants a guaranteed-fresh reading
    calls `snapshot_claude_env()` directly.
    """
    global _env_snapshot_cache, _env_snapshot_at
    now = time.time()
    if now - _env_snapshot_at >= _ENV_SNAPSHOT_TTL_S:
        _env_snapshot_cache = snapshot_claude_env()
        _env_snapshot_at = now
    return _env_snapshot_cache


def read_claude_env_once(pid: int) -> tuple[bool, Optional[int]]:
    """(carries a Claude marker, parsed CLAUDE_PID owner) for one pid.

    THE SINGLE READ both `has_claude_env` and `read_claude_pid` need, and
    the reason it exists is COST: the kill path consults BOTH channels
    for every row, and two separate `ps eww` spawns per row is one wasted
    subprocess per row on a host with a thousand processes. MEASURED on
    the owner host: `ps eww -o command= -p <pid>` costs ~25 ms.

    The batched snapshot answers for almost every pid; a pid the snapshot
    does not hold is read DIRECTLY, so a process that started after the
    snapshot was taken is still answered correctly rather than being
    reported as unknown.

    The TWO ANSWERS come from the SAME read because the two channels read
    the SAME environment block: the marker test asks "is any
    `CLAUDE_ENV_MARKERS` name present as a `NAME=value` token?", and the
    pointer test asks "what is the value of the `CLAUDE_PID` token?".

    Only a `NAME=value` TOKEN counts, for the reason `has_claude_env`
    documents: `ps eww` returns the ARGV and the ENVIRONMENT concatenated
    with no separator, so a bare `CLAUDECODE` in the command line is not
    an environment variable.
    """
    hit = cached_claude_env().get(pid)
    if hit is not None:
        return hit
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ps", "eww", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None
    if out.returncode != 0:
        return False, None
    marker = False
    owner: Optional[int] = None
    for token in out.stdout.split():
        name, sep, value = token.partition("=")
        if not sep:
            continue
        if name in CLAUDE_ENV_MARKERS:
            marker = True
        elif name == CLAUDE_PID_ENV and owner is None:
            owner = parse_claude_pid_value(value, own_pid=pid)
    return marker, owner
def has_claude_env(pid: int) -> bool:
    """True iff the process's OWN environment carries a Claude marker.

    This is the attribution channel that survives reparenting. Read it
    with `ps eww -o command= -p <pid>` — the environment is appended to
    the command line, so it comes back in the same read.

    Only the CANDIDATES are probed: on a host with 1400 processes, asking
    every process for its environment would cost 1400 subprocess spawns
    per beat.

    ONLY A `NAME=value` TOKEN COUNTS, and that restriction is
    load-bearing. `ps eww` returns the ARGV and the ENVIRONMENT
    concatenated with no separator between them, so a naive scan for the
    marker as a bare word credits any process whose COMMAND LINE merely
    mentions the string — a filename, a URL, a git branch, a grep
    pattern. MEASURED on this host: this very session's `ps eww` output
    contains the token `"CLAUDECODE\\|CLAUDE_PROJECT_DIR"` — and that
    token came from the COMMAND LINE of the `grep` that was asking the
    question, not from any environment variable at all. A probe that
    matched bare words would have classified that grep as agent-started.

    The real environment variables appear as `NAME=value` tokens
    appended AFTER the argv — MEASURED: `CLAUDECODE=1`,
    `MY_MARKER_VAR=hello`. So the rule is: a token whose NAME (the part
    before the first `=`) is a marker. A bare `CLAUDECODE` with no `=` is
    part of the argv and is ignored.

    WHAT THE SIGNAL PROVES, precisely — and this is narrower than
    "started by an agent". The environment is INHERITED, so a marker
    means the process DESCENDS FROM a Claude Code session. A command the
    user typed at a plain shell prompt inherits a shell environment with
    no markers, so it is not attributed. But a terminal the user opened
    FROM INSIDE a session, and everything they run in it, DOES carry the
    markers — that is the same inheritance, one generation further down.
    So the honest claim is "descends from a Claude Code session", and
    the shape allowlist plus the age gate are what turn that into
    "kill-worthy".
    """
    return read_claude_env_once(pid)[0]
def claude_ancestor(pid: int, table: dict[int, tuple[int, str]]) -> Optional[int]:
    """Pid of the nearest ancestor whose executable is CLAUDE-FAMILY.

    The SECOND, weaker owner-resolution channel. It cannot see a
    reparented process at all (which is the abandoned-watcher case), so it
    is never the only channel -- but a descendant of a `claude` session IS
    Claude-related, and the shape allowlist still has to agree.

    THE CASE TEST IS CASE-INSENSITIVE, and that is a SAFETY property, not
    a style choice. The previous test was
    `basename in ("claude", "claude.exe")` -- LOWERCASE ONLY. MEASURED on
    the owner host: Claude Desktop is installed as a binary named `Claude`
    (CAPITAL C) at /Applications/Claude.app/Contents/MacOS/Claude. So a
    live Claude Desktop session's descendants had NO claude-named
    ancestor, and under the old NEGATED abandonment rule they read as
    ABANDONED. A live session the user is working in must never be
    killable, and the case of the first letter of a filename was enough to
    break that.

    Stops at pid <= 1, a cycle, a missing parent, or 64 levels.
    """
    seen = {pid}
    cur = pid
    for _ in range(64):
        entry = table.get(cur)
        if entry is None:
            return None
        ppid = entry[0]
        if ppid <= 1 or ppid in seen:
            return None
        parent = table.get(ppid)
        if parent is None:
            return None
        words = parent[1].split(None, 1)
        if words and is_claude_family_executable(words[0]):
            return ppid
        seen.add(ppid)
        cur = ppid
    return None


def is_claude_family_executable(argv0: str) -> bool:
    """True iff the given argv[0] names a CLAUDE-FAMILY executable.

    The basename is compared, CASE-INSENSITIVELY, against
    `CLAUDE_FAMILY_EXECUTABLES`. The comparison is case-insensitive
    because the Claude DESKTOP binary is spelled with a capital C
    (MEASURED: /Applications/Claude.app/Contents/MacOS/Claude) and a
    lowercase-only test did not match it -- see `claude_ancestor`.
    """
    base = os.path.basename(argv0).lower()
    return base in _CLAUDE_FAMILY_LOWER


def read_claude_pid(pid: int) -> Optional[int]:
    """The parsed `CLAUDE_PID` owner pid carried by the LIVE process `pid`.

    THE POSITIVE OWNER POINTER (TRDD-ZIKYQQY0 A-1). MEASURED on the owner
    host: `CLAUDE_PID` is a descendant->session pointer in the process
    ENVIRONMENT, and it SURVIVES reparenting -- which is exactly the case
    the ancestry channel cannot see at all. That is the whole reason this
    function exists: the ancestry channel is a NEGATIVE signal about the
    tree, and this is a POSITIVE statement about the owner.

    Read with the SAME `ps eww -o command= -p <pid>` discipline as
    `has_claude_env` -- the environment comes back appended to the command
    line, so it comes back in the same read.

    ONLY A `NAME=value` TOKEN COUNTS, and that restriction is
    load-bearing for the same reason it is in `has_claude_env`: `ps eww`
    returns the ARGV and the ENVIRONMENT concatenated with no separator,
    so a bare `CLAUDE_PID` with no `=` is part of the argv and is ignored.
    MEASURED on the owner host, the real environment carries
    `CLAUDE_PID=20716` as a token.

    THE VALUE MUST BE A REAL PID, and three things are rejected for a
    reason each:

      * a NON-NUMERIC value -- MEASURED template artefact: the literal
        token `CLAUDE_PID={v}` exists on this host, and a shell command
        line containing `CLAUDE_PID=[0-9]*` exists too. Neither is a
        pointer, and a template artefact read as an owner would point the
        liveness test at a pid that means nothing;
      * a value that is not a PLAUSIBLE pid -- it must satisfy
        `1 < value < 2**31`. `kern.maxproc` is 16000 on this host, so
        real pids are far below the ceiling, and pid 0 and pid 1 are
        `kernel_task` and `launchd` -- never a Claude session;
      * a value EQUAL TO THE PROCESS'S OWN PID -- a self-pointer is not an
        owner, and treating it as one would make a process its own
        (permanently "alive" or, worse, "dead") owner.

    None means "no owner pointer could be read", and the caller must treat
    that as UNKNOWN -- never as "the owner is dead".
    """
    return read_claude_env_once(pid)[1]


def parse_claude_pid_value(raw: str, *, own_pid: Optional[int] = None) -> Optional[int]:
    """Parse a `CLAUDE_PID` VALUE into a plausible owner pid, or None.

    THE PARSER-LEVEL SEAM, so the template-artefact rules are testable
    without a live process. `read_claude_pid` is the reader; this is the
    rule the value must satisfy.

    Rejected, each for a measured reason (see `read_claude_pid`):
    non-numeric values (the `CLAUDE_PID={v}` template artefact), values
    outside `1 < value < 2**31`, and a value equal to the process's own
    pid (a self-pointer is not an owner).
    """
    text = raw.strip()
    if not text.isdigit():
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    if not (1 < value < 2 ** 31):
        return None
    if own_pid is not None and value == own_pid:
        return None
    return value


def claude_owner_pid(
    row: ProcRow,
    ancestry: dict[int, tuple[int, str]],
    *,
    owner_probe=None,
) -> Optional[int]:
    """The Claude OWNER pid of `row`, or None when the owner is UNKNOWN.

    RESOLUTION, IN ORDER:

      1. the parsed `CLAUDE_PID` from the process's OWN environment -- the
         POSITIVE pointer, and the only channel that survives
         reparenting;
      2. else the nearest CLAUDE-FAMILY ancestor -- the fallback, and the
         channel that cannot see a reparented process at all;
      3. else None -- UNKNOWN.

    UNKNOWN IS NOT "DEAD". The caller must refuse the kill on an unknown
    owner; see `is_abandoned`.

    `owner_probe` is an INJECTION SEAM, exactly like `env_probe`, so the
    rule is testable without a subprocess per row. Its default is the
    real `read_claude_pid`.
    """
    probe = owner_probe if owner_probe is not None else read_claude_pid
    pointed = probe(row.pid)
    if pointed is not None:
        return pointed
    return claude_ancestor(row.pid, ancestry)


class OwnerProbeError(RuntimeError):
    """The owner-liveness probe could not READ the process table.

    Distinct from ABSENT (`read_owner_comm` returning None): a probe that
    cannot answer must never be read as "the owner is dead" -- see
    `owner_state` and TRDD-ZIKYQQY0 A-1.
    """


def read_owner_comm(pid: int) -> Optional[str]:
    """The owner pid's `comm` NAME if PRESENT, None if ABSENT; may raise OwnerProbeError.

    THE REAL LIVENESS PROBE: `ps -p <pid> -o comm=` -- a SINGLE pid, so
    there is no subprocess storm.

    The SHAPE of the answer is the point: a NAME means the pid is PRESENT
    in the process table, and None means it is ABSENT. The caller does the
    family test on the name; this function never decides liveness on its
    own, because "the pid exists" is not the same claim as "the owner is
    alive" -- see `owner_state`.

    None (ABSENT) is returned ONLY for the one measured absent-pid shape:
    rc 1 with empty stdout AND empty stderr. Every other outcome -- a pid
    <= 0, a failed spawn, a timeout, any other rc, any stderr, or rc 0 with
    empty stdout -- raises OwnerProbeError.
    """
    # WHY (TRDD-ZIKYQQY0 A-1): a probe that cannot read the table must never
    # read as a dead owner, because "dead" authorizes a kill. Previously every
    # failure returned None (== ABSENT == dead), so a ps outage or timeout made
    # live sessions' children killable. pid 0 is indistinguishable from an
    # absent pid in ps output (MEASURED), so it is refused up front.
    if pid <= 0:
        raise OwnerProbeError(f"invalid owner pid {pid}")
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OwnerProbeError(f"ps probe for pid {pid} failed: {exc}") from exc
    name = out.stdout.strip()
    stderr = out.stderr.strip()
    if out.returncode == 0 and name:
        # `ps -o comm=` prints the executable path on macOS for some binaries
        # (MEASURED: /sbin/launchd, .../bin/esbuild), so the BASENAME is what
        # the family test needs.
        return os.path.basename(name)
    # ABSENT shape: MEASURED on macOS (rc 1, nothing on stdout or stderr);
    # Linux procps is believed to behave identically but is not measured here.
    if out.returncode == 1 and not name and not stderr:
        return None
    raise OwnerProbeError(
        f"ps probe for pid {pid} unreadable: rc={out.returncode} stderr={stderr!r}"
    )


def owner_state(owner_pid: int, liveness_probe=None) -> str:
    """One of "dead", "alive", "unknown", "probe-failed" -- the liveness test.

    THE THREE CASES, and why a two-case test is a bug:

      (a) the owner pid is ABSENT from the process table -> "dead" -> the
          process IS abandoned, and the kill proceeds;
      (b) the owner pid is PRESENT and its name is a CLAUDE-FAMILY name
          -> "alive" -> the session is running, and the kill is REFUSED;
      (c) the owner pid is PRESENT but its name is NOT Claude-family ->
          "unknown" -> the pid was RECYCLED, so the real owner is gone,
          but the pointer can no longer PROVE it -> the kill is REFUSED.

    THE FOURTH STATE, "probe-failed": the probe raised OwnerProbeError
    (the process table could not be read). Liveness is UNPROVEN, so the
    kill is REFUSED. It is deliberately not "unknown": a persistent ps
    failure must not be reported as pid reuse.

    Case (c) is a SAFETY requirement, not a nicety. `kern.maxproc` is
    16000 on the owner host, so pids ARE recycled: a dead owner's pid is
    eventually handed to an unrelated process. A liveness test that only
    asks "does the pid exist" sees "yes" in case (c), concludes "the
    session is alive", and REFUSES the orphan FOREVER -- so the guard
    reads as inert, which is the exact symptom the card has been
    fighting. But treating case (c) as "dead" would kill the work of
    whatever process now holds that pid. So case (c) reads UNKNOWN, and
    UNKNOWN always fails SAFE.

    `liveness_probe` is the INJECTION SEAM: it returns the owner pid's
    `comm` NAME if the pid is PRESENT, or None if the pid is ABSENT, or
    raises OwnerProbeError if it cannot tell. Its default is the real
    `read_owner_comm`.
    """
    probe = liveness_probe if liveness_probe is not None else read_owner_comm
    # WHY (TRDD-ZIKYQQY0 A-1): an unreadable process table must fail SAFE,
    # never fall through to the None -> "dead" branch below.
    try:
        name = probe(owner_pid)
    except OwnerProbeError:
        return "probe-failed"
    if name is None:
        return "dead"
    if is_claude_family_executable(name):
        return "alive"
    return "unknown"


def is_abandoned(
    row: ProcRow,
    ancestry: dict[int, tuple[int, str]],
    *,
    owner_pid: Optional[int] = None,
    owner_probe=None,
    liveness_probe=None,
) -> bool:
    """True iff the Claude owner of this process is POSITIVELY IDENTIFIED
    and PROVABLY DEAD.

    THE POLARITY, CORRECTED (TRDD-ZIKYQQY0 A-1). The previous rule was
    the NEGATION of the attribution channel: "abandoned" meant "there is
    NO live `claude` session ancestor". Two things were wrong with that.

    FIRST, the ancestry channel was INCAPABLE of producing a kill. The
    attribution clause is "the env probe says yes OR a claude ancestor
    exists", and the abandonment clause was "no claude ancestor exists" --
    so a process attributed BY ancestry could never be a victim. The
    channel that was supposed to catch a reparented orphan was the same
    channel the rule used to exclude it.

    SECOND, and worse, the rule was "kill unless PROVEN Claude-owned",
    which is the INVERSE of the owner's directive. MEASURED: Claude
    Desktop is installed on this host as a binary named `Claude` (CAPITAL
    C), so a live Desktop session's descendants had no `claude`-named
    ancestor and read as ABANDONED.

    THE RULE NOW, and every UNKNOWN fails SAFE:

      * owner identified AND provably dead -> ABANDONED (the kill may
        proceed);
      * owner identified AND alive -> not abandoned (the kill is refused);
      * owner identified AND its pid was RECYCLED -> not abandoned;
      * NO owner identified -> not abandoned.

    The ANCESTRY TABLE is no longer consulted as a NEGATIVE test. It is
    consulted only as the FALLBACK way to find an owner, and an empty
    table therefore does not mean "abandoned" -- it means the fallback
    cannot resolve an owner, while the environment pointer still can.
    """
    owner = owner_pid
    if owner is None:
        owner = claude_owner_pid(row, ancestry, owner_probe=owner_probe)
    if owner is None:
        return False  # UNKNOWN owner -> never abandoned
    return owner_state(owner, liveness_probe) == "dead"


def parse_ps_table(text: str) -> dict[int, tuple[int, str]]:
    """Parse `ps -axo pid=,ppid=,command=` into {pid: (ppid, command)}."""
    table: dict[int, tuple[int, str]] = {}
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        table[pid] = (ppid, parts[2])
    return table

# WHERE macOS KEEPS ITS SWAPFILES, and the per-file size it uses. Both
# are MEASURED on this host (2026-10-20) as an unprivileged user:
#
#   /System/Volumes/VM/swapfile0 .. swapfile7  (7 files, a GAP at 5)
#   each exactly 1073741824 bytes = vm.compressor.swapper.swapfile_size_max
#
# The count must be BY FILE, never by name index: the gap at 5 means a
# "how many indexes up to the highest" count would over-count by one.
SWAPFILE_DIR = "/System/Volumes/VM"
SWAPFILE_GLOB = "swapfile*"


def count_swapfiles(directory: str = SWAPFILE_DIR) -> Optional[int]:
    """The number of swapfile FILES in the VM volume, or None = unknown.

    The count the 2026-10-20 panic named ('69 swapfiles') was
    previously unreadable on macOS, so the `swapfiles` arm of
    `host_pressure` was UNREACHABLE — a threshold that can never fire
    is a threshold that does not exist, and the docstring said so
    instead of reading the real thing.

    It IS readable: macOS keeps the swapfiles as ordinary files on the
    VM volume, and the directory is world-readable
    (`drwxr-xr-x root wheel`), so the listing needs no privilege.

    None when the directory is absent or unreadable — never a guess.
    A wrong count flips a healthy host to critical, and a count of 0
    is a plausible reading on a host with no swap at all, so the
    absence of the directory is reported as UNKNOWN rather than 0.
    """
    try:
        entries = [
            name for name in os.listdir(directory)
            if name.startswith("swapfile")
        ]
    except OSError:
        return None
    if not entries:
        return None
    return len(entries)


def swapfile_size_bytes() -> Optional[int]:
    """The size of ONE swapfile in bytes, or None = unknown.

    `vm.compressor.swapper.swapfile_size_max` is the value macOS sizes
    its swapfiles at, and it is the cross-check that makes the file
    COUNT trustworthy: count x per-file-size must equal the swap
    TOTAL that `vm.swapusage` reports. MEASURED here: 7 files x
    1073741824 bytes = 7 x 1 GiB = 7168 MB, and
    `vm.swapusage` reports total = 7168.00M. EXACT MATCH.
    """
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["sysctl", "-n", "vm.compressor.swapper.swapfile_size_max"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None

def swapfile_total_matches_count(
    count: Optional[int],
    per_file_bytes: Optional[int],
    total_mb: Optional[int],
) -> Optional[bool]:
    """Do the counted swapfiles account for the reported swap total?

    THE CROSS-CHECK, and it is what makes the COUNT trustworthy. On
    this host (MEASURED 2026-10-20) there are 7 swapfile files, each
    exactly 1073741824 bytes, and `vm.swapusage` reports total =
    7168.00M — 7 x 1 GiB = 7168 MB, an EXACT MATCH. A count that
    disagreed with the total would mean one of the two readings is
    wrong, and the guard must not act on a reading it cannot trust.

    None when any of the three figures is UNKNOWN: an unmeasured
    quantity is not a passing check, it is an absent one, and the
    caller must not read "None" as "the check passed".
    """
    if count is None or per_file_bytes is None or total_mb is None:
        return None
    if count <= 0 or per_file_bytes <= 0:
        return None
    expected_mb = count * per_file_bytes // (1024 * 1024)
    return expected_mb == total_mb


def refusal_reason(
    row: ProcRow,
    *,
    protected_pids: frozenset[int],
    min_etime_s: int,
    ancestry: dict[int, tuple[int, str]],
    env_probe=None,
    owner_probe=None,
    liveness_probe=None,
    env_snapshot: Optional[dict[int, tuple[bool, Optional[int]]]] = None,
) -> Optional[str]:
    """The kill-path clause that REFUSES this row, as a short stable token.

    None means the row is KILLABLE. The tokens are stable, short, and
    machine-greppable — they are what the alert path reports, so the
    owner can see WHY the guard stood down without parsing prose.

    THE CLAUSE SEQUENCE, and every clause is a REFUSAL — each one fails
    SAFE:

      1. "protected-pid"     — the daemon, its parent, the janitor itself;
      2. "janitor-own"       — the janitor's OWN installation (A-6);
      3. "not-claude-owned"  — ownership NOT PROVEN: no Claude env marker
         AND no claude-family ancestor;
      4. "forbidden-client"  — another AI client the owner forbade;
      5. "interactive-session" — an interactive `claude` / Claude Desktop
         session the user is typing into;
      6. "no-runaway-shape"  — not on the POSITIVE shape allowlist;
      7. "too-young"         — below the runaway age gate (floored at
         MIN_RUNAWAY_ETIME_S);
      8. "owner-unknown"     — the owner could not be POSITIVELY IDENTIFIED;
      9. "owner-alive"       — the owner is alive;
     10. "owner-recycled"    — the owner pid is present but its name is not
         Claude-family, so the pid was RECYCLED and the pointer can no
         longer prove anything.
     11. "owner-probe-failed" — the liveness probe could not read the
         process table, so the owner's state is UNPROVEN.

    Clause 3 is the "PROVEN Claude-owned" half of the owner directive and
    it stays a HARD GATE, before the shape and age gates. The ENV PROBE is
    an INHERITANCE test, so a process started by a foreign client from a
    Claude-spawned shell inherits the markers and is indistinguishable by
    that channel alone — the forbidden-client list is what refuses the
    NAMED ones, and the shape allowlist is what bounds the rest.

    Clauses 8, 9 and 10 are the CORRECTED abandonment rule: the owner
    must be positively identified AND provably dead. An UNKNOWN owner
    (clause 8) and a RECYCLED owner (clause 10) both REFUSE.

    `env_probe`, `owner_probe` and `liveness_probe` are the INJECTION
    SEAMS, so the rule is testable without a subprocess per row. Their
    defaults are the real probes. `env_snapshot` is an optional
    PRE-READ batched environment map; when given it answers BOTH the
    marker test and the owner pointer for every row, and no per-pid
    probe is spawned at all.
    """
    if row.pid in protected_pids:
        return "protected-pid"
    if is_janitor_own(row.command):
        return "janitor-own"
    ancestor = claude_ancestor(row.pid, ancestry)
    marker, pointed = _marker_and_pointer(row.pid, env_probe, owner_probe, env_snapshot)
    if not (marker or ancestor is not None):
        return "not-claude-owned"
    if is_forbidden_client(row.command):
        return "forbidden-client"
    if is_interactive_claude(row.command):
        return "interactive-session"
    if not any(sig.search(row.command) for sig in RUNAWAY_SHAPES):
        return "no-runaway-shape"
    # THE AGE GATE HAS A FLOOR (TRDD-ZIKYQQY0 A-0). The knob may be
    # raised, never lowered: a caller that passes 0 gets the floor, so
    # no configuration can turn the age gate off entirely.
    if row.etime_s < max(min_etime_s, MIN_RUNAWAY_ETIME_S):
        return "too-young"
    # THE OWNER, resolved in the spec's order: the parsed `CLAUDE_PID`
    # pointer first, else the claude-family ancestor.
    owner = pointed if pointed is not None else ancestor
    if owner is None:
        return "owner-unknown"
    state = owner_state(owner, liveness_probe)
    if state == "alive":
        return "owner-alive"
    if state == "unknown":
        return "owner-recycled"
    if state == "probe-failed":
        return "owner-probe-failed"
    return None  # the owner is PROVABLY DEAD -> the row is killable


def _marker_and_pointer(
    pid: int,
    env_probe,
    owner_probe,
    env_snapshot: Optional[dict[int, tuple[bool, Optional[int]]]] = None,
) -> tuple[bool, Optional[int]]:
    """(carries a Claude marker, parsed CLAUDE_PID owner) for one pid.

    ONE read when the channels are the real ones, and one call per
    injected seam otherwise. The injection is what makes the rule
    testable without a subprocess per row, and a test that injects only
    one of the two seams must still get the REAL answer for the other.

    A PRE-READ `env_snapshot` short-circuits both: it is the batched
    reading of the whole host, and it answers both questions at once.
    """
    if env_snapshot is not None:
        hit = env_snapshot.get(pid)
        if hit is not None:
            return hit
    if env_probe is None and owner_probe is None:
        return read_claude_env_once(pid)
    marker = env_probe(pid) if env_probe is not None else has_claude_env(pid)
    pointed = owner_probe(pid) if owner_probe is not None else read_claude_pid(pid)
    return marker, pointed


def is_killable(
    row: ProcRow,
    *,
    protected_pids: frozenset[int],
    min_etime_s: int,
    ancestry: dict[int, tuple[int, str]],
    env_probe=None,
    owner_probe=None,
    liveness_probe=None,
    env_snapshot: Optional[dict[int, tuple[bool, Optional[int]]]] = None,
) -> bool:
    """The whole truth table. Every clause must pass.

    The clause sequence and the reasons live in `refusal_reason`, which
    is the single place the truth table is evaluated: `is_killable` is
    "no clause refused", and the alert path is "which clause refused".
    One evaluation, two consumers, no chance of the two disagreeing.

    `env_probe`, `owner_probe` and `liveness_probe` are injected so the
    rule is testable without spawning a subprocess per row; they default
    to the real environment, owner-pointer and liveness probes.
    """
    return refusal_reason(
        row,
        protected_pids=protected_pids,
        min_etime_s=min_etime_s,
        ancestry=ancestry,
        env_probe=env_probe,
        owner_probe=owner_probe,
        liveness_probe=liveness_probe,
        env_snapshot=env_snapshot,
    ) is None


def select_victim(
    rows: list[ProcRow],
    *,
    protected_pids: frozenset[int],
    min_etime_s: int = DEFAULT_RUNAWAY_ETIME_S,
    ancestry: Optional[dict[int, tuple[int, str]]] = None,
    env_probe=None,
    owner_probe=None,
    liveness_probe=None,
    env_snapshot: Optional[dict[int, tuple[bool, Optional[int]]]] = None,
) -> Optional[ProcRow]:
    """Pick the single largest-RSS killable row, or None.

    ONE victim per call. The guard kills at most one process per beat and
    re-evaluates pressure on the next beat, so a transient misread can
    never cascade into a kill spree.
    """
    table = ancestry if ancestry is not None else {}
    candidates = [
        r for r in rows
        if is_killable(
            r,
            protected_pids=protected_pids,
            min_etime_s=min_etime_s,
            ancestry=table,
            env_probe=env_probe,
            owner_probe=owner_probe,
            liveness_probe=liveness_probe,
            env_snapshot=env_snapshot,
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.rss_kb)


def select_refused_alert_with_reason(
    rows: list[ProcRow],
    *,
    protected_pids: frozenset[int],
    min_rss_kb: int = DEFAULT_ALERT_RSS_KB,
    ancestry: Optional[dict[int, tuple[int, str]]] = None,
    env_probe=None,
    owner_probe=None,
    liveness_probe=None,
    env_snapshot: Optional[dict[int, tuple[bool, Optional[int]]]] = None,
) -> Optional[tuple[ProcRow, str]]:
    """The largest process the kill path REFUSES, with the reason, or None.

    THE ALERT IS EVERY REFUSAL, not just two of them. It used to select
    only processes refused by `is_forbidden_client` or
    `is_interactive_claude`, which is the two categories refused BY
    POLICY. It was SILENT about the far more common category: a huge
    process that is simply UNATTRIBUTED, or not yet abandoned, or
    forbidden for a reason the owner has never heard of. MEASURED on the
    owner host: the largest real hog is `alcore serve` at 1 545 MB, and
    under the old rule the guard would have said NOTHING about it — the
    daemon would have stood down in silence while a 1.5 GB process grew.

    THE REASON IS A SHORT STABLE TOKEN, not a sentence: "not-claude-owned",
    "owner-alive", "forbidden-client", "too-young" and so on. A token
    is greppable and comparable; a sentence is neither, and a reason that
    reads differently every time is not a reason a reader can learn.

    THE AGE FLOOR IS GONE, and that is the point (TRDD-ZIKYQQY0 A-1,
    item 12). The floor's stated purpose is to bound the KILL SURFACE,
    and this path has no kill surface: it reports, it does not act. The
    floor used to silence the alert about a 9 GB `codex --serve` that was
    TEN SECONDS old — precisely the "enormous but young" case the alert
    exists for. MEASURED: both the kill path and the alert path were
    handed `min_etime_s = 3600`, so the alert path silently gained a
    one-hour age floor it never had.

    The `min_rss_kb` bar remains: the alert is about the processes big
    enough to matter, and a report about every refused process would be a
    report about every process.
    """
    table = ancestry if ancestry is not None else {}
    refused: list[tuple[ProcRow, str]] = []
    for row in rows:
        if row.rss_kb < min_rss_kb:
            continue
        reason = refusal_reason(
            row,
            protected_pids=protected_pids,
            min_etime_s=MIN_RUNAWAY_ETIME_S,
            ancestry=table,
            env_probe=env_probe,
            owner_probe=owner_probe,
            liveness_probe=liveness_probe,
            env_snapshot=env_snapshot,
        )
        if reason is not None:
            refused.append((row, reason))
    if not refused:
        return None
    return max(refused, key=lambda pair: pair[0].rss_kb)


def select_refused_alert(
    rows: list[ProcRow],
    *,
    protected_pids: frozenset[int],
    min_rss_kb: int = DEFAULT_ALERT_RSS_KB,
    ancestry: Optional[dict[int, tuple[int, str]]] = None,
    env_probe=None,
    owner_probe=None,
    liveness_probe=None,
    env_snapshot: Optional[dict[int, tuple[bool, Optional[int]]]] = None,
) -> Optional[ProcRow]:
    """The largest process the guard REFUSES to kill, for the owner's eyes.

    Alert-only. A process this large that the guard will not kill is
    exactly the runaway shape — a system daemon growing silently while
    the never-kill invariant (rightly) holds. Standing down must not mean
    silence about it.

    THE REASON-CARRYING SIBLING IS `select_refused_alert_with_reason`,
    and this function is the row-only view of it. Both evaluate the SAME
    clause sequence, so the two can never disagree about which process is
    the largest refused one.
    """
    found = select_refused_alert_with_reason(
        rows,
        protected_pids=protected_pids,
        min_rss_kb=min_rss_kb,
        ancestry=ancestry,
        env_probe=env_probe,
        owner_probe=owner_probe,
        liveness_probe=liveness_probe,
        env_snapshot=env_snapshot,
    )
    return None if found is None else found[0]


# ---------- I/O edges -------------------------------------------------------

def snapshot_processes(snapshot_path: str) -> list[ProcRow]:
    """`ps -axo pid,ppid,rss,etime,command` -> FILE -> parsed rows.

    The file hop is deliberate (the no-self-match discipline): the
    snapshot is complete before any matching happens, and the file
    doubles as the forensic record of what the guard saw when it acted.
    """
    try:
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["ps", "-axo", "pid,ppid,rss,etime,command"],
                stdout=fh, stderr=subprocess.DEVNULL, timeout=20, check=False,
            )
        if proc.returncode != 0:
            return []
        with open(snapshot_path, encoding="utf-8") as fh:
            return parse_ps_snapshot(fh.read())
    except (OSError, subprocess.SubprocessError):
        return []


def snapshot_ancestry(snapshot_path: str) -> dict[int, tuple[int, str]]:
    """`ps -axo pid=,ppid=,command=` -> {pid: (ppid, command)}.

    A SECOND snapshot, for the ancestry channel. It is a separate call
    because the two tables want different column sets and the guard only
    needs ancestry for the CANDIDATES — but the table must be built for
    the whole host, since a candidate's ancestor may be any pid.
    """
    try:
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["ps", "-axo", "pid=,ppid=,command="],
                stdout=fh, stderr=subprocess.DEVNULL, timeout=20, check=False,
            )
        if proc.returncode != 0:
            return {}
        with open(snapshot_path, encoding="utf-8") as fh:
            return parse_ps_table(fh.read())
    except (OSError, subprocess.SubprocessError):
        return {}


def kill_process(pid: int, *, term_grace_s: float = 2.0) -> bool:
    """SIGTERM -> grace -> SIGKILL. True iff the process is gone afterwards."""
    import signal  # noqa: PLC0415 - only needed on the kill path
    import time  # noqa: PLC0415

    def _alive(target: int) -> bool:
        try:
            os.kill(target, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return not _alive(pid)
    deadline = time.time() + term_grace_s
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return not _alive(pid)
    time.sleep(0.2)
    return not _alive(pid)


def base_name(command: str) -> str:
    """The process's BASE NAME — never its full command line.

    The broadcast payload is host-level and identical for every project
    (TRDD-X92VBFNF). A command line like `pytest /Volumes/.../other-
    project/tests` would carry one project's content into every other
    project's session, so the broadcast copy carries only the basename.
    """
    parts = command.split()
    if not parts:
        return "?"
    name = os.path.basename(parts[0])
    return name or "?"
