"""IOC taxonomy primitives — distilled from the deep-forensics-ioc audit
(see reports/study-github-monitoring-deep/*deep-forensics-ioc*.md).

Pure-Python stdlib API surface; YAML parsing piggybacks on PyYAML when a
caller has already declared it in their PEP 723 block (matches the
pattern already used by `scripts/lib/sentinel/model.py` and
`scripts/detectors/package-manager-policy.py`). When PyYAML is absent
the loader raises `IOCTaxonomyError` with a clear remediation message
rather than silently returning a partial structure.

Public surface (every name documented + tested):

  * IOCRecord                         — NamedTuple bundling one threat's
                                        IOC quadrants (vulnerabilitieschecker
                                        AUDIT.md pattern: c2 + fs + persist
                                        + disguise + filename masquerades).
  * parse_ioc_yaml(path)              — load a per-threat YAML bundle into
                                        a list[IOCRecord].
  * MBC_BEHAVIOUR_TAGS                — frozenset of Malware Behavior
                                        Catalog v3.1 namespace labels
                                        (malcontent rules/* taxonomy).
  * EXPOSURE_VS_COMPROMISE_LABELS     — frozenset of the four posture
                                        states distinguishing "lockfile
                                        match only" from "active C2".
  * IR_STAGE_ADVISORIES               — mapping of canonical IR stage →
                                        advisory string.
  * incident_response_advisory(stage) — return the canonical advisory for
                                        an IR stage (isolate / snapshot /
                                        contain-persistence / rotate /
                                        block-c2 / audit-workflows).

Convergent design references:
  * `vulnerabilitieschecker-main/AUDIT.md` — IOC quadrant breakdown.
  * `malcontent-main/rules/*/` — MBC behaviour categories (1 dir = 1 tag).
  * `tocsin-main/src/core/types.ts` — exposure-vs-compromise vocabulary.
  * `supply-chain-defense-skills-main/skills/.../SKILL.md` — IR order
    (isolate → snapshot → contain-persistence → rotate → block-c2).

Iron rule — all primitives are pure / deterministic / side-effect-free
EXCEPT the loader, which performs read-only I/O exactly once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, NamedTuple

# ---- Error type ----------------------------------------------------------


class IOCTaxonomyError(RuntimeError):
    """Raised when an IOC bundle cannot be parsed.

    Distinct from `ValueError` / `FileNotFoundError` so callers can catch
    *taxonomy* failures (malformed bundle) separately from generic I/O
    failures (file missing, permission denied).
    """


# ---- Core record type ----------------------------------------------------


class IOCRecord(NamedTuple):
    """Per-threat IOC bundle — the four-quadrant breakdown distilled from
    `vulnerabilitieschecker-main/AUDIT.md`.

    Every Shai-Hulud-class incident leaves residue in at least one of
    these quadrants, which is why this shape (c2 / fs / persist /
    disguise) is the complete cover an IR responder needs.

    Fields:
        threat_id   — stable identifier, e.g. "T001_axios" or
                      "SCJ-2026-05-tanstack-react-router". Used as a
                      dedupe key across heartbeats.
        name        — human-readable title (one line, no colons; matches
                      TRDD title style for grep-friendliness).
        package     — affected package name in its ecosystem-native
                      spelling (e.g. "@tanstack/react-router",
                      "requests", "log4j-core").
        versions    — tuple of affected version strings. Tuple (not list)
                      so the record stays hashable and can live in sets.
        c2          — outbound network indicators keyed by category, at
                      minimum the literals "dom" / "ip" / "port". Empty
                      string = unknown / not applicable.
        ioc_fs      — per-OS filesystem indicators, keyed by sys.platform
                      values ("darwin" / "win32" / "linux"). Each value
                      is a tuple of literal paths (no globs at this
                      layer — globs are a separate detector concern).
        persist     — per-OS persistence mechanism description, keyed by
                      sys.platform values ("darwin" / "win32" / "linux").
                      Value is a free-text mechanism label like
                      "LaunchAgent plist" or "systemd-user unit".
        disguise    — tuple of filename masquerades (what the attacker
                      named things to look benign), e.g.
                      ("codeql_analysis.yml", "gh-token-monitor.sh").
        published   — disclosure date in ISO 8601 "YYYY-MM-DD" form.
        references  — tuple of authoritative URLs (Snyk write-up, OSV
                      advisory page, GHSA page).

    Note on hashability: the c2/ioc_fs/persist fields are dicts (chosen
    over frozenset[tuple[str,str]] for ergonomic .get() access in
    detectors), so IOCRecord instances are NOT hashable. Cross-detector
    dedupe across heartbeats should key on `threat_id` (a str), which IS
    hashable.
    """

    threat_id: str
    name: str
    package: str
    versions: tuple[str, ...]
    c2: dict[str, str]
    ioc_fs: dict[str, tuple[str, ...]]
    persist: dict[str, str]
    disguise: tuple[str, ...]
    published: str
    references: tuple[str, ...]


# ---- MBC v3.1 behaviour categories ---------------------------------------


# Malware Behavior Catalog v3.1 namespace labels — mirrors
# `malcontent-main/rules/*/` directory taxonomy (25 sibling directories,
# each is a behaviour category). Kept as the directory-level granularity
# a janitor detector can actually attribute. ATT&CK technique IDs are
# orthogonal and belong on a different field.
MBC_BEHAVIOUR_TAGS: Final[frozenset[str]] = frozenset({
    "anti-behavior",  # evading dynamic analysis / sandbox detection
    "anti-static",    # obfuscation, packing, string-encoding
    "c2",             # command-and-control beacon / callback channel
    "collect",        # credential / file / token harvesting
    "credential",     # specifically credential theft (subset of collect)
    "crypto",         # cryptographic primitives — often miner or ransom
    "discover",       # reconnaissance — env, network, mounted volumes
    "evasion",        # process hiding, file hiding, log wiping
    "exec",           # arbitrary code execution
    "exfil",          # outbound data transfer
    "fs",             # filesystem manipulation (drop, replace, delete)
    "impact",         # destructive — wiper, encryption, defacement
    "lateral",        # lateral movement / propagation
    "mem",            # in-memory injection / process hollowing
    "net",            # outbound network not tagged c2/exfil
    "os",             # OS-level — kernel modules, syscall hooks
    "persist",        # boot-survival
    "privesc",        # privilege escalation
    "process",        # process manipulation
    "sec-tool",       # disabling security tooling
    "sus",            # suspicious — references "malicious", "1337", etc.
})


# ---- Exposure-vs-compromise posture vocabulary ---------------------------


# Posture states distinguishing "IOC pattern matches in the project" from
# "compromise is actively executing." See
# `vulnerabilitieschecker-main/README.md` Step 0 (exposure) vs Steps 1-4
# (compromise). The janitor's posture.py letter-grade is severity-only;
# this set adds an orthogonal dimension surfacing whether IR is needed
# RIGHT NOW.
EXPOSURE_VS_COMPROMISE_LABELS: Final[frozenset[str]] = frozenset({
    "EXPOSED",
    # IOC pattern matches in the project but no execution evidence yet —
    # e.g. compromised version pinned in package.json, but `node_modules/`
    # doesn't exist OR shows the file but no persistence-locator hits.
    "POSSIBLY_COMPROMISED",
    # One IOC of any category hits — e.g. the suspect package is installed
    # in node_modules but no fs/persist/c2 IOC has been observed yet.
    "COMPROMISED",
    # ≥ 1 ioc_fs hit OR ioc_persist hit AND the suspect package is in the
    # dependency closure (causal chain is plausible).
    "ACTIVE_THREAT",
    # ioc_persist file exists AND ioc_c2 traffic observed (e.g. LaunchAgent
    # plist + /etc/hosts shows the C2 domain was queried).
})


# ---- IR-stage advisory strings -------------------------------------------


# Canonical IR-stage advisories. The four-stage order
# (isolate → snapshot → contain-persistence → rotate → block-c2 →
# audit-workflows) is the convergent recommendation across
# `vulnerabilitieschecker-main/AUDIT.md` (steps 0-5) and
# `supply-chain-defense-skills-main/SKILL.md` (steps 1-3). The
# isolate-BEFORE-rotate ordering is the single most important
# safety property: rotating tokens on a compromised host trips a
# wiper / dead-man-switch IF the malware has a "revoke detection"
# trigger (observed in real Shai-Hulud variants).
IR_STAGE_ADVISORIES: Final[dict[str, str]] = {
    "isolate": (
        "Step 1 — isolate the workstation: disconnect from network now. "
        "Do NOT rotate tokens or remove persistence first — wiper / "
        "dead-man-switch risk on credential revoke."
    ),
    "snapshot": (
        "Step 2 — forensic snapshot before any cleanup: copy node_modules, "
        "LaunchAgents, .github/workflows, and shell-init files to "
        ".janitor-forensic/<ts>/ so the responder can reconstruct the "
        "compromise after persistence is removed."
    ),
    "contain-persistence": (
        "Step 3 — stop persistence mechanisms: launchctl unload the "
        "compromised plist, systemctl --user disable the compromised "
        "unit, remove .claude/settings.json hook entries referencing the "
        "dropped files. Do NOT delete the files yet — forensics needs "
        "them; just stop them from re-executing on next login."
    ),
    "rotate": (
        "Step 4 — rotate credentials in the canonical order: "
        "(1) npm publish tokens + OIDC trusted-publisher grants, "
        "(2) GitHub PATs (classic + fine-grained), "
        "(3) AWS access keys, (4) HashiCorp Vault tokens, "
        "(5) Kubernetes service-account tokens, (6) SSH private keys, "
        "(7) GCP service-account credentials, "
        "(8) Claude Code session logs (~/.claude/projects/*/conversation*.jsonl). "
        "Order matters — rotating Vault before npm OIDC can re-issue "
        "tokens from the wrong identity chain."
    ),
    "block-c2": (
        "Step 5 — block outbound C2: add ioc_c2 domains to /etc/hosts "
        "(127.0.0.1 sinkhole) AND to the DNS resolver's blocklist. "
        "Domain-level blocks are not enough for catbox-style stagers — "
        "block the full payload URL at the egress proxy if you have one."
    ),
    "audit-workflows": (
        "Step 6 — audit .github/workflows/ for injected entries: any file "
        "not committed by the project author or referenced in package.json "
        "is suspect. Compromised codeql_analysis.yml is the canonical "
        "tanstack-react-router 2026-05 disguise."
    ),
}


def incident_response_advisory(stage: str) -> str:
    """Return the canonical advisory string for an IR stage.

    Stages map 1:1 to the keys of IR_STAGE_ADVISORIES. Unknown stages
    raise IOCTaxonomyError (fail-fast — a typo in the stage name should
    not silently return an empty / fallback string that ends up in the
    user's heartbeat as a no-op).

    Stages:
        "isolate"             — disconnect network; do NOT touch creds
        "snapshot"            — forensic copy before any cleanup
        "contain-persistence" — stop persistence without deleting it yet
        "rotate"              — 8-step credential rotation order
        "block-c2"            — DNS + hosts + egress proxy
        "audit-workflows"     — sweep .github/workflows/ for injection
    """
    if stage not in IR_STAGE_ADVISORIES:
        raise IOCTaxonomyError(
            f"unknown IR stage {stage!r} — valid stages are "
            f"{sorted(IR_STAGE_ADVISORIES)}"
        )
    return IR_STAGE_ADVISORIES[stage]


# ---- YAML loader ---------------------------------------------------------


# Shape we accept from a per-threat YAML file. Top-level may be either a
# list of records or a single record (treated as a one-element list) —
# matches the `vulnerabilitieschecker-main/AUDIT.md` pattern where each
# .yaml is one threat, plus the more common "incidents.yaml lists every
# threat we know about" packaging.
_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "threat_id",
    "name",
    "package",
    "versions",
    "c2",
    "ioc_fs",
    "persist",
    "disguise",
    "published",
    "references",
)


def _coerce_str_tuple(value: object, field: str) -> tuple[str, ...]:
    """Coerce a YAML list of strings into a tuple[str, ...]; reject
    everything else so a malformed bundle fails fast at parse time
    instead of producing a corrupt IOCRecord that breaks downstream
    detectors with cryptic AttributeErrors.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise IOCTaxonomyError(
            f"field {field!r} must be a YAML list, got {type(value).__name__}"
        )
    for item in value:
        if not isinstance(item, str):
            raise IOCTaxonomyError(
                f"field {field!r} entries must be strings, got "
                f"{type(item).__name__}: {item!r}"
            )
    return tuple(value)


def _coerce_str_dict(value: object, field: str) -> dict[str, str]:
    """Coerce a YAML mapping of str→str. Empty mapping is allowed."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IOCTaxonomyError(
            f"field {field!r} must be a YAML mapping, got {type(value).__name__}"
        )
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise IOCTaxonomyError(
                f"field {field!r} keys must be strings, got {type(k).__name__}"
            )
        # YAML may parse port numbers as int — accept them as str.
        out[k] = str(v) if v is not None else ""
    return out


def _coerce_str_tuple_dict(value: object, field: str) -> dict[str, tuple[str, ...]]:
    """Coerce a YAML mapping of str→list[str] into str→tuple[str, ...]."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IOCTaxonomyError(
            f"field {field!r} must be a YAML mapping, got {type(value).__name__}"
        )
    out: dict[str, tuple[str, ...]] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise IOCTaxonomyError(
                f"field {field!r} keys must be strings, got {type(k).__name__}"
            )
        out[k] = _coerce_str_tuple(v, f"{field}.{k}")
    return out


def _record_from_mapping(raw: dict[str, object]) -> IOCRecord:
    """Build one IOCRecord from a parsed-YAML mapping. Validates all
    required fields are present; coerces types; raises IOCTaxonomyError
    on any deviation.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise IOCTaxonomyError(
            f"IOC record missing required fields: {missing} "
            f"(threat_id={raw.get('threat_id', '?')!r})"
        )

    threat_id = raw["threat_id"]
    if not isinstance(threat_id, str) or not threat_id:
        raise IOCTaxonomyError(
            f"field 'threat_id' must be a non-empty string, got {threat_id!r}"
        )
    name = raw["name"]
    if not isinstance(name, str) or not name:
        raise IOCTaxonomyError(
            f"field 'name' must be a non-empty string, got {name!r}"
        )
    package = raw["package"]
    if not isinstance(package, str) or not package:
        raise IOCTaxonomyError(
            f"field 'package' must be a non-empty string, got {package!r}"
        )
    published = raw["published"]
    if not isinstance(published, str) or not published:
        raise IOCTaxonomyError(
            f"field 'published' must be a non-empty ISO 8601 date string, "
            f"got {published!r}"
        )

    return IOCRecord(
        threat_id=threat_id,
        name=name,
        package=package,
        versions=_coerce_str_tuple(raw["versions"], "versions"),
        c2=_coerce_str_dict(raw["c2"], "c2"),
        ioc_fs=_coerce_str_tuple_dict(raw["ioc_fs"], "ioc_fs"),
        persist=_coerce_str_dict(raw["persist"], "persist"),
        disguise=_coerce_str_tuple(raw["disguise"], "disguise"),
        published=published,
        references=_coerce_str_tuple(raw["references"], "references"),
    )


def parse_ioc_yaml(path: Path) -> list[IOCRecord]:
    """Load a per-threat IOC bundle (or a list of bundles) from `path`.

    Accepts two top-level shapes:
      * a single mapping  → returns a one-element list[IOCRecord]
      * a list of mappings → returns the parsed list verbatim

    Raises:
      FileNotFoundError — `path` doesn't exist or isn't a file.
      IOCTaxonomyError  — PyYAML missing, YAML malformed, or any record
                          fails the schema validation in
                          `_record_from_mapping()`.

    PyYAML is intentionally imported INSIDE the function so importers of
    this module that never call the loader (e.g. detectors that only need
    the constants + advisory function) don't pay the optional-dep cost.
    """
    if not path.is_file():
        raise FileNotFoundError(f"IOC bundle not found: {path}")

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:
        raise IOCTaxonomyError(
            "PyYAML is required to parse IOC bundles. Declare it in your "
            "script's PEP 723 block: dependencies = ['pyyaml>=6.0']"
        ) from exc

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise IOCTaxonomyError(f"malformed YAML in {path}: {exc}") from exc

    if raw is None:
        # Empty file. Treat as no records (not an error — the caller may
        # be merging multiple bundles and an empty one contributes zero).
        return []
    if isinstance(raw, dict):
        return [_record_from_mapping(raw)]
    if isinstance(raw, list):
        records: list[IOCRecord] = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise IOCTaxonomyError(
                    f"IOC bundle {path} entry #{i} must be a YAML mapping, "
                    f"got {type(entry).__name__}"
                )
            records.append(_record_from_mapping(entry))
        return records

    raise IOCTaxonomyError(
        f"IOC bundle {path} top-level must be a mapping or list of mappings, "
        f"got {type(raw).__name__}"
    )
