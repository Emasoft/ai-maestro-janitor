"""Shared helpers of the real-bun tests of the secrets-shield redact and restore (TRDD-BAQB9SYO increment 3, steps 3a-2 and 3a-4b).

`Box` holds the folders of one test (root, out, home, vault, global git config) and the commands that run in them; `Scan` is the result of one scanner run. Every child runs with SECRETS_SHIELD_VAULT_DIR set under tmp_path, so no test can write the real vault.
Every fake credential is generated at call time by `_fake_secrets`, so no contiguous credential literal sits in this file (see tests/test_secret_fixture_hygiene.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import transcript_redact as tr
from _fake_secrets import secret

SHIELD = Path(__file__).resolve().parents[1] / "scripts" / "shield_scan"
SCAN = SHIELD / "scan.ts"
VAULT = SHIELD / "vault.ts"
REDACT = SHIELD / "redact.ts"
TIMEOUT_S = 180.0
TOKEN = secret("gh" + "p_", "redact-1", 36)
TOKEN2 = secret("gh" + "p_", "redact-2", 36)
AT = chr(64)
MARKER_RE = re.compile(r"\[REDACTED-BY-SECRET-SHIELD\. Type: ([A-Za-z0-9_-]+)\. ID: ([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\]")


class Scan:
    """The result of one scanner run: exit code, both streams, and the records of the findings file when it was written."""

    def __init__(self, done: subprocess.CompletedProcess[str], out: Path) -> None:
        self.code = done.returncode
        self.stdout = done.stdout
        self.stderr = done.stderr
        self.out = out
        self.records: list[dict[str, Any]] = []
        if out.exists():
            self.records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    @property
    def summary(self) -> dict[str, Any]:
        """The last record of the findings file."""
        # why: explicit raise, not assert: the check must survive python -O
        if self.records[-1]["type"] != "summary":
            raise AssertionError("the last record of the findings file must be the summary")
        return self.records[-1]

    @property
    def skips(self) -> list[tuple[str, str]]:
        """Every skip record as (path, reason), in file order."""
        return [(r["path"], r["reason"]) for r in self.records if r["type"] == "skip"]

    def streams(self) -> str:
        """Everything the run wrote that a person could read: stdout, stderr and the findings file."""
        return self.stdout + self.stderr + (self.out.read_text(encoding="utf-8") if self.out.exists() else "")


class Box:
    """One test's folders (root, out, home, vault, global git config) and the commands that run in them."""

    def __init__(self, base: Path) -> None:
        self.base = base.resolve()
        self.root = self.base / "root"
        self.root.mkdir()
        self.home_dir = self.base / "home"
        self.home_dir.mkdir()
        self.vault_dir = self.base / "vault"
        self.gitconfig = self.base / "gitconfig"
        self.gitconfig.write_text(f"[user]\n\tname = redact test\n\temail = redact{AT}example.test\n", encoding="utf-8")
        self.runs = 0

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """The environment of every child: HOME, the global git config and the vault folder are the test's own."""
        env = dict(os.environ)
        env.update({"HOME": str(self.home_dir), "GIT_CONFIG_GLOBAL": str(self.gitconfig), "GIT_CONFIG_NOSYSTEM": "1", "SECRETS_SHIELD_VAULT_DIR": str(self.vault_dir)})
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(name, None)
        env.update(extra or {})
        return env

    def git(self, cwd: Path, *args: str) -> str:
        """Run git in cwd and return its stdout; a failure raises."""
        done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env())
        return done.stdout

    def put(self, path: Path, text: str | bytes) -> Path:
        """Write a file, creating its folders."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8", newline="")
        return path

    def repo(self, path: Path, *tracked: str) -> Path:
        """Make a git repo at path and commit the named files (relative to path)."""
        path.mkdir(parents=True, exist_ok=True)
        self.git(path, "init", "-q")
        if tracked:
            self.git(path, "add", "-f", "--", *tracked)
            self.git(path, "commit", "-q", "-m", "c")
        return path

    def run(self, *args: str, root: Path | None = None, min_age: str | None = "0", env_extra: dict[str, str] | None = None) -> Scan:
        """Run the scanner with --redact over root (default: the box root), 2 jobs and an explicit findings file under the box."""
        self.runs += 1
        out_path = self.base / "out" / f"run{self.runs}.jsonl"
        cmd = [tr.resolve_bun(), str(SCAN), "--jobs", "2", "--out", str(out_path), "--redact"]
        if min_age is not None:
            cmd += ["--min-age-minutes", min_age]
        cmd += [*args, str(root or self.root)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(env_extra), check=False)
        return Scan(done, out_path)

    def bun_json(self, script: str, data: object) -> Any:
        """Run a `bun -e` script that reads one JSON value from stdin and prints one JSON value."""
        done = subprocess.run([tr.resolve_bun(), "-e", script], input=json.dumps(data), capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(), check=True)
        return json.loads(done.stdout)

    def vault_rows(self) -> list[dict[str, Any]]:
        """Every vault row (uuid, type, origin, encoding, count, value)."""
        script = f"import {{ openVault }} from {json.dumps(str(VAULT))}; await Bun.stdin.text(); const v = openVault(); console.log(JSON.stringify(v.list().map((m) => ({{ ...m, value: v.byUuid(m.uuid)?.value }})))); v.close()"
        rows: list[dict[str, Any]] = self.bun_json(script, None)
        return rows

    def restore(self, text: str) -> str:
        """The text with every shield marker replaced by the value of its vault row (what restore.ts will do in step 3a-4)."""
        script = f"import {{ openVault }} from {json.dumps(str(VAULT))}; const uuids = JSON.parse(await Bun.stdin.text()); const v = openVault(); const out = {{}}; for (const u of uuids) out[u] = v.byUuid(u)?.value ?? null; console.log(JSON.stringify(out)); v.close()"
        values: dict[str, str | None] = self.bun_json(script, sorted({m.group(2) for m in MARKER_RE.finditer(text)}))

        def put_back(m: re.Match[str]) -> str:
            value = values[m.group(2)]
            # why: explicit raise, not assert: the check must survive python -O
            if value is None:
                raise AssertionError("a marker has no vault row")
            return value

        return MARKER_RE.sub(put_back, text)


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")
