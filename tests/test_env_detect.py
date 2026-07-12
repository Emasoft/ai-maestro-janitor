"""Tests for the PURE environment-detection primitives in scripts/lib/env_detect.py.

Real, no mocks. Every function under test is pure: it takes a synthetic env dict,
injected which/exists callables, or a raw command-output string, and returns a
plain dict/list. So the tests construct inputs by hand and assert the return
value — NO real host, NO subprocess. The load-bearing invariant these tests pin
is that a diagnostic which reads credential-adjacent state NEVER emits a secret
VALUE: the SECURITY tests below prove masking of proxies/MCP URLs/credential env
vars, culminating in a dedicated no-secret-leak assertion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import env_detect as ed  # noqa: E402


def _no(*_: object) -> bool:
    """A which/exists stub that reports everything absent."""
    return False


def _only(*names: str):
    """Build a which/exists stub that reports True only for `names`."""
    wanted = set(names)
    return lambda x: x in wanted


# --- is_secret_key ----------------------------------------------------------


def test_is_secret_key_credential_names_true():
    """Names matching KEY/TOKEN/SECRET/PASSWORD are secret-bearing (True)."""
    for name in ("OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD"):
        assert ed.is_secret_key(name) is True


def test_is_secret_key_allowlist_and_plain_false():
    """AWS_PROFILE/AWS_REGION are allow-listed and a plain name is not secret (False)."""
    assert ed.is_secret_key("AWS_PROFILE") is False
    assert ed.is_secret_key("AWS_REGION") is False
    assert ed.is_secret_key("EDITOR") is False


# --- env_value --------------------------------------------------------------


def test_env_value_secret_key_returns_none():
    """A secret key never returns its VALUE, even when set."""
    assert ed.env_value({"GITHUB_TOKEN": "ghp_live"}, "GITHUB_TOKEN") is None


def test_env_value_safe_value_and_absent_none():
    """A safe key returns its value; an absent key returns None."""
    assert ed.env_value({"EDITOR": "vim"}, "EDITOR") == "vim"
    assert ed.env_value({"EDITOR": "vim"}, "PAGER") is None


# --- mask_proxy -------------------------------------------------------------


def test_mask_proxy_strips_scheme_credentials():
    """http://user:pass@host:3128 has its embedded credentials stripped."""
    assert ed.mask_proxy("http://alice:s3cr3t@host:3128") == "http://host:3128"


def test_mask_proxy_strips_bare_credentials():
    """A bare user:pass@host form (no scheme) is also credential-stripped."""
    assert ed.mask_proxy("alice:s3cr3t@host") == "host"


def test_mask_proxy_plain_url_unchanged():
    """A credential-free proxy URL passes through unchanged."""
    assert ed.mask_proxy("http://host:8080") == "http://host:8080"


def test_mask_proxy_empty_returns_empty():
    """An empty proxy value maps to the empty string."""
    assert ed.mask_proxy("") == ""


# --- detect_terminal --------------------------------------------------------


def test_detect_terminal_env_signals_and_kind():
    """WT_SESSION→Windows Terminal, TERM_PROGRAM=iTerm.app→iTerm2, ancestry kind echoed, iterm session flagged."""
    wt = ed.detect_terminal({"WT_SESSION": "abc"})
    assert wt["env_signal"] == "Windows Terminal"
    assert wt["program"] == "Windows Terminal"

    it = ed.detect_terminal(
        {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0"}, ancestry_kind="tmux"
    )
    assert it["program"] == "iTerm2"
    assert it["kind"] == "tmux"
    assert it["iterm_session_present"] is True


# --- detect_multiplexer -----------------------------------------------------


def test_detect_multiplexer_tmux():
    """TMUX_PANE identifies a tmux multiplexer and carries the pane id."""
    m = ed.detect_multiplexer({"TMUX_PANE": "%3"})
    assert m == {"kind": "tmux", "pane": "%3"}


def test_detect_multiplexer_screen():
    """STY identifies a GNU screen multiplexer."""
    m = ed.detect_multiplexer({"STY": "1234.pts-0.host"})
    assert m is not None and m["kind"] == "screen"


def test_detect_multiplexer_zellij():
    """ZELLIJ identifies a zellij multiplexer."""
    m = ed.detect_multiplexer({"ZELLIJ": "0"})
    assert m is not None and m["kind"] == "zellij"


def test_detect_multiplexer_none_when_bare():
    """No multiplexer env vars → None."""
    assert ed.detect_multiplexer({}) is None


# --- detect_wsl -------------------------------------------------------------


def test_detect_wsl_microsoft_and_none():
    """'microsoft' in /proc/version → a WSL dict; absent → None."""
    d = ed.detect_wsl({}, proc_version="Linux version 5.15 Microsoft WSL2")
    assert d is not None and d["version"] == "WSL2"
    assert ed.detect_wsl({}, proc_version="Linux version 6.0 generic") is None


# --- parse_mount_fstype -----------------------------------------------------


def test_parse_mount_fstype_longest_prefix_wins():
    """The mountpoint that is the LONGEST prefix of the target decides the fstype."""
    text = (
        "/dev/disk1s1 on / (apfs, local, journaled)\n"
        "/dev/disk2 on /Volumes/Data (nfs, remote)"
    )
    assert ed.parse_mount_fstype(text, "/Volumes/Data/file") == "nfs"
    assert ed.parse_mount_fstype(text, "/etc/hosts") == "apfs"


# --- filesystem_is_network --------------------------------------------------


def test_filesystem_is_network_nfs_smbfs_true_apfs_false():
    """nfs/smbfs are network filesystems; apfs is local."""
    assert ed.filesystem_is_network("nfs") is True
    assert ed.filesystem_is_network("smbfs") is True
    assert ed.filesystem_is_network("apfs") is False


# --- detect_ci --------------------------------------------------------------


def test_detect_ci_github_actions_with_details():
    """GITHUB_ACTIONS → provider GitHub Actions plus a non-secret github detail dict."""
    ci = ed.detect_ci({
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_WORKFLOW": "CI",
    })
    assert ci is not None
    assert ci["provider"] == "GitHub Actions"
    assert ci["github"]["repository"] == "owner/repo"
    assert ci["github"]["workflow"] == "CI"


def test_detect_ci_gitlab():
    """GITLAB_CI → provider GitLab CI (no github detail block)."""
    ci = ed.detect_ci({"GITLAB_CI": "true"})
    assert ci is not None
    assert ci["provider"] == "GitLab CI"
    assert "github" not in ci


def test_detect_ci_bare_generic():
    """A bare CI flag with no recognised provider → generic CI."""
    ci = ed.detect_ci({"CI": "true"})
    assert ci is not None
    assert ci["provider"] == "generic CI (unidentified provider)"


def test_detect_ci_none_when_absent():
    """No CI signals → None."""
    assert ed.detect_ci({"HOME": "/home/u"}) is None


# --- detect_containers ------------------------------------------------------


def test_detect_containers_codespaces():
    """CODESPACES env marker is reported and labels its source var ($CODESPACES)."""
    sig = ed.detect_containers({"CODESPACES": "true"}, exists=_no, virt="")
    assert any("$CODESPACES" in s for s in sig)


def test_detect_containers_dockerenv():
    """An existing /.dockerenv marker file → a docker signal."""
    sig = ed.detect_containers({}, exists=_only("/.dockerenv"), virt="")
    assert any("docker" in s for s in sig)


def test_detect_containers_virt_kvm():
    """systemd-detect-virt 'kvm' → a KVM VM virtualization signal."""
    sig = ed.detect_containers({}, exists=_no, virt="kvm")
    assert any("KVM VM" in s for s in sig)


def test_detect_containers_empty_on_bare():
    """No markers, no env, no virt → an empty signal list."""
    assert ed.detect_containers({}, exists=_no, virt="") == []


# --- detect_ide -------------------------------------------------------------


def test_detect_ide_vscode_and_claude_code():
    """TERM_PROGRAM=vscode → VS Code; CLAUDECODE set → Claude Code with a surface."""
    vs = ed.detect_ide({"TERM_PROGRAM": "vscode"})
    assert vs["editor"] == "VS Code"

    cc = ed.detect_ide({"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert cc["claude"]["is_claude_code"] is True
    assert cc["claude"]["surface"] == "CLI / terminal"


# --- detect_execution_context ----------------------------------------------


def test_detect_execution_context_headless_and_worktree():
    """No TTY → headless True; a differing git_dir/git_common_dir → linked worktree, equal → not."""
    h = ed.detect_execution_context({}, has_tty=False)
    assert h["headless"] is True
    assert h["interactive_tty"] is False

    linked = ed.detect_execution_context(
        {}, has_tty=True, git_dir="/repo/.git/worktrees/wt", git_common_dir="/repo/.git"
    )
    assert linked["linked_worktree"] is True

    same = ed.detect_execution_context(
        {}, has_tty=True, git_dir="/repo/.git", git_common_dir="/repo/.git"
    )
    assert same["linked_worktree"] is False


# --- detect_proxies ---------------------------------------------------------


def test_detect_proxies_masks_and_no_proxy():
    """HTTPS_PROXY credentials are masked; NO_PROXY (a host list) passes through."""
    out = ed.detect_proxies({
        "HTTPS_PROXY": "http://alice:s3cr3t@proxy:8443",
        "NO_PROXY": "localhost,127.0.0.1",
    })
    assert out["HTTPS_PROXY"] == "http://proxy:8443"
    assert out["NO_PROXY"] == "localhost,127.0.0.1"
    assert "s3cr3t" not in json.dumps(out)


# --- parse_interfaces -------------------------------------------------------


def test_parse_interfaces_ifconfig_and_ip():
    """An ifconfig block and an `ip -o addr` line each parse to {name, addrs}."""
    ifconfig = "en0: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 192.168.1.5 netmask 0xffffff00"
    got = ed.parse_interfaces(ifconfig, system="Darwin")
    assert {"name": "en0", "addrs": ["192.168.1.5"]} in got

    iproute = "3: eth0    inet 10.0.0.2/24 brd 10.0.0.255 scope global eth0"
    got2 = ed.parse_interfaces(iproute, system="Linux")
    assert got2 == [{"name": "eth0", "addrs": ["10.0.0.2"]}]


# --- detect_vpn -------------------------------------------------------------


def test_detect_vpn_tailscale():
    """A tailscale0 interface OR a 100.64/10 CGNAT address flags Tailscale."""
    by_name = ed.detect_vpn([{"name": "tailscale0", "addrs": ["100.101.102.103"]}], which=_no)
    assert by_name["tailscale"] is True
    assert "Tailscale" in by_name["kinds"]

    by_addr = ed.detect_vpn([{"name": "utun3", "addrs": ["100.64.1.2"]}], which=_no)
    assert by_addr["tailscale"] is True


def test_detect_vpn_wireguard_and_openvpn():
    """A wg0 interface → WireGuard; which('openvpn') → OpenVPN (installed)."""
    wg = ed.detect_vpn([{"name": "wg0", "addrs": ["10.9.0.1"]}], which=_no)
    assert "WireGuard" in wg["kinds"]

    ovpn = ed.detect_vpn([], which=_only("openvpn"))
    assert "OpenVPN (installed)" in ovpn["kinds"]


# --- classify_nat -----------------------------------------------------------


def test_classify_nat_behind_nat_true():
    """Only private LAN IPv4 (192.168.x on en0) → behind NAT (True)."""
    assert ed.classify_nat([{"name": "en0", "addrs": ["192.168.1.5"]}]) is True


def test_classify_nat_global_ip_false_and_empty_none():
    """A globally-routable IPv4 → not behind NAT (False); nothing to judge → None."""
    assert ed.classify_nat([{"name": "en0", "addrs": ["8.8.8.8"]}]) is False
    assert ed.classify_nat([]) is None


def test_classify_nat_tailscale_does_not_flip():
    """A Tailscale 100.64/10 addr on a utun interface must NOT flip the LAN to public (still True)."""
    ifaces = [
        {"name": "en0", "addrs": ["192.168.1.5"]},
        {"name": "utun3", "addrs": ["100.64.1.2"]},
    ]
    assert ed.classify_nat(ifaces) is True


# --- parse_default_gateway --------------------------------------------------


def test_parse_default_gateway_macos_and_linux():
    """Both `route -n get default` (macOS) and `ip route` (Linux) spellings parse."""
    assert ed.parse_default_gateway("   gateway: 192.168.1.1\n   interface: en0") == "192.168.1.1"
    assert ed.parse_default_gateway("default via 10.0.0.1 dev eth0") == "10.0.0.1"


# --- parse_dns_servers ------------------------------------------------------


def test_parse_dns_servers_dedupe_both_formats():
    """scutil `nameserver[N] :` and resolv.conf `nameserver` both parse, deduped in order."""
    text = "nameserver[0] : 8.8.8.8\nnameserver 8.8.8.8\nnameserver 1.1.1.1"
    assert ed.parse_dns_servers(text) == ["8.8.8.8", "1.1.1.1"]


# --- parse_firewall_state ---------------------------------------------------


def test_parse_firewall_state_variants():
    """macos-alf enabled/state=0, ufw active, and an empty probe each classify correctly."""
    assert ed.parse_firewall_state("Firewall is enabled.", kind="macos-alf") == "enabled"
    assert ed.parse_firewall_state("state = 0", kind="macos-alf") == "disabled"
    assert ed.parse_firewall_state("Status: active", kind="ufw") == "enabled"
    assert ed.parse_firewall_state("", kind="macos-alf") == "unknown (not readable / needs root)"


# --- parse_listening_ports --------------------------------------------------


def test_parse_listening_ports_lsof_and_ss():
    """An lsof loopback LISTEN line and an ss 0.0.0.0 LISTEN line parse with correct `exposed`."""
    text = (
        "node  123 user  22u  IPv4 0x0  0t0  TCP 127.0.0.1:3000 (LISTEN)\n"
        'LISTEN 0      511          0.0.0.0:8080      0.0.0.0:*    users:(("nginx",pid=1,fd=6))'
    )
    ports = ed.parse_listening_ports(text)
    by_port = {p["port"]: p for p in ports}
    assert by_port["3000"]["exposed"] is False
    assert by_port["3000"]["process"] == "node"
    assert by_port["8080"]["exposed"] is True
    assert by_port["8080"]["process"] == "nginx"


# --- detect_python_env ------------------------------------------------------


def test_detect_python_env_venv_and_conda():
    """VIRTUAL_ENV yields the venv name; CONDA_DEFAULT_ENV yields the conda env."""
    venv = ed.detect_python_env({"VIRTUAL_ENV": "/home/u/venvs/myproj"})
    assert venv["virtualenv"]["name"] == "myproj"

    conda = ed.detect_python_env({"CONDA_DEFAULT_ENV": "base"})
    assert conda["conda"] == "base"


# --- detect_cloud -----------------------------------------------------------


def test_detect_cloud_credentials_presence_only():
    """AWS credential presence is flagged (True) without the value; GCP project shown; bare → {}."""
    aws = ed.detect_cloud({"AWS_ACCESS_KEY_ID": "AKIAFOO"}, which=_no, exists=_no)
    assert aws["aws"]["credentials_in_env"] is True
    assert "AKIAFOO" not in json.dumps(aws)

    gcp = ed.detect_cloud({"GOOGLE_CLOUD_PROJECT": "my-proj"}, which=_no, exists=_no)
    assert gcp["gcp"]["project"] == "my-proj"

    assert ed.detect_cloud({}, which=_no, exists=_no) == {}


# --- detect_user ------------------------------------------------------------


def test_detect_user_sudo_and_admin():
    """SUDO_USER → sudo True + sudo_from; injected is_admin is passed through."""
    u = ed.detect_user({"SUDO_USER": "alice", "USER": "root"}, is_admin=True)
    assert u["sudo"] is True
    assert u["sudo_from"] == "alice"
    assert u["is_admin"] is True


# --- detect_path ------------------------------------------------------------


def test_detect_path_counts_and_notable():
    """PATH entries are counted and notable prefixes (homebrew/cargo) flagged."""
    p = ed.detect_path({"PATH": "/usr/bin:/opt/homebrew/bin:/home/u/.cargo/bin"})
    assert p["count"] == 3
    assert p["notable"]["homebrew"] is True
    assert p["notable"]["cargo"] is True


# --- detect_present ---------------------------------------------------------


def test_detect_present_only_which_true_with_version():
    """Only binaries `which` resolves are included, with an injected version string."""
    table = (("git", "git"), ("docker", "Docker"))
    got = ed.detect_present(table, which=_only("git"), versions={"git": "2.42.0"})
    assert got == [{"binary": "git", "label": "git", "version": "2.42.0"}]


# --- detect_mcp_servers -----------------------------------------------------


def test_detect_mcp_servers_secret_safe():
    """A stdio and an http MCP server flatten to name+transport+endpoint — never token/env/args."""
    configs = [(
        "proj",
        {"mcpServers": {
            "local": {"command": "/usr/bin/node", "args": ["server.js"]},
            "remote": {"url": "https://api.example.com/mcp?token=SECRET", "env": {"API_KEY": "leakme"}},
        }},
    )]
    out = ed.detect_mcp_servers(configs)
    blob = json.dumps(out)
    assert "SECRET" not in blob
    assert "token=" not in blob
    assert "leakme" not in blob
    assert "API_KEY" not in blob
    assert "server.js" not in blob
    by_name = {s["name"]: s for s in out}
    assert by_name["local"]["endpoint"] == "node"
    assert by_name["remote"]["endpoint"] == "https://api.example.com"


# --- detect_subscription ----------------------------------------------------


def test_detect_subscription_api_key_and_oauth():
    """ANTHROPIC_API_KEY → API auth mode (value never emitted); CLAUDECODE → OAuth subscription."""
    api = ed.detect_subscription({"ANTHROPIC_API_KEY": "sk-ant-fake"})
    assert api["auth_mode"] == "API key (pay-as-you-go)"
    assert "sk-ant-fake" not in json.dumps(api)

    oauth = ed.detect_subscription({"CLAUDECODE": "1"})
    assert oauth["auth_mode"] == "Claude subscription (OAuth login)"
    assert "needs a live account probe" in oauth["tier"]


def test_detect_subscription_unknown_when_bare():
    """No Claude/Anthropic auth signals → unknown auth mode and tier."""
    assert ed.detect_subscription({}) == {"auth_mode": "unknown", "tier": "unknown"}


# --- CRITICAL: no secret VALUE ever reaches an output -----------------------


def test_secret_safety_no_secret_values_leak():
    """No fake secret (env creds, MCP url token, MCP env value) appears in any detector output."""
    env = {"AWS_SECRET_ACCESS_KEY": "AKIAFAKE", "GITHUB_TOKEN": "ghp_fake"}
    configs = [(
        "src",
        {"mcpServers": {"r": {"url": "https://h/mcp?token=topsecret", "env": {"API_KEY": "leakme"}}}},
    )]
    # Secret-bearing env keys must never yield a value.
    assert ed.env_value(env, "AWS_SECRET_ACCESS_KEY") is None
    assert ed.env_value(env, "GITHUB_TOKEN") is None

    outputs = [
        [ed.env_value(env, k) for k in env],
        ed.detect_cloud(env, which=_no, exists=_no),
        ed.detect_ci(env),
        ed.detect_mcp_servers(configs),
    ]
    blob = json.dumps(outputs, default=str)
    for leak in ("AKIAFAKE", "ghp_fake", "topsecret", "leakme"):
        assert leak not in blob


# --- wave 2: git / GitHub / plugins parsers ---------------------------------


def test_github_slug_forms():
    """https / ssh / git@ github URLs → owner/repo (with .git stripped); non-github → None."""
    assert ed.github_slug("https://github.com/Owner/Repo.git") == "Owner/Repo"
    assert ed.github_slug("git@github.com:Owner/Repo.git") == "Owner/Repo"
    assert ed.github_slug("ssh://git@github.com/Owner/Repo") == "Owner/Repo"
    assert ed.github_slug("https://gitlab.com/o/r.git") is None
    assert ed.github_slug("") is None


def test_parse_git_config_remotes_desc_hookspath():
    """A .git/config parses remotes, branch descriptions, and core.hooksPath."""
    text = (
        '[remote "origin"]\n\turl = https://github.com/Emasoft/x.git\n'
        '[branch "main"]\n\tdescription = the trunk\n'
        "[core]\n\thooksPath = .githooks\n"
    )
    cfg = ed.parse_git_config(text)
    assert cfg["remotes"]["origin"] == "https://github.com/Emasoft/x.git"
    assert cfg["branch_descriptions"]["main"] == "the trunk"
    assert cfg["hooks_path"] == ".githooks"


def test_parse_git_config_empty():
    """An empty config yields empty maps and no hooks path."""
    cfg = ed.parse_git_config("")
    assert cfg == {"remotes": {}, "branch_descriptions": {}, "hooks_path": None}


def test_parse_branches():
    """for-each-ref lines parse into {name,last_commit,upstream,subject}."""
    text = ("main|2026-07-13 01:00:00 +0200|origin/main|feat: x\n"
            "dev|2026-07-10 09:00:00 +0200||wip")
    got = ed.parse_branches(text)
    assert got[0] == {"name": "main", "last_commit": "2026-07-13 01:00:00 +0200",
                      "upstream": "origin/main", "subject": "feat: x"}
    assert got[1]["upstream"] == ""


def test_active_git_hooks_excludes_samples_and_nonexec():
    """Active hooks are non-.sample AND executable per the injected is_exec."""
    entries = ["pre-commit", "pre-push.sample", "commit-msg", "README"]
    execset = {"pre-commit", "commit-msg"}
    assert ed.active_git_hooks(entries, lambda n: n in execset) == ["commit-msg", "pre-commit"]


def test_summarize_rulesets():
    """Ruleset payloads summarize to name/target/enforcement/branches/rule_types."""
    rulesets = [{
        "name": "baseline-history-protect", "target": "branch", "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    }]
    got = ed.summarize_rulesets(rulesets)
    assert got[0]["name"] == "baseline-history-protect"
    assert got[0]["enforcement"] == "active"
    assert got[0]["branches"] == ["~DEFAULT_BRANCH"]
    assert got[0]["rule_types"] == ["deletion", "non_fast_forward"]


def test_summarize_rulesets_tolerates_sparse():
    """A ruleset missing conditions/rules still summarizes without raising."""
    got = ed.summarize_rulesets([{"name": "x", "target": "branch", "enforcement": "evaluate"}])
    assert got[0]["branches"] == [] and got[0]["rule_types"] == []


def test_version_stale():
    """Semver comparison → up-to-date / stale / unknown."""
    assert ed.version_stale("0.41.0", "0.41.0") == "up-to-date"
    assert ed.version_stale("0.41.0", "0.42.0") == "stale (0.42.0 available)"
    assert ed.version_stale("0.42.0", "0.41.0") == "up-to-date"
    assert ed.version_stale("", "0.42.0") == "unknown"


def test_parse_enabled_plugins_counts_and_marketplaces():
    """enabledPlugins map → installed/enabled/disabled counts + per-marketplace tally."""
    enabled = {
        "a@mkt1": True, "b@mkt1": False, "c@mkt2": True, "d": True,
    }
    out = ed.parse_enabled_plugins(enabled)
    assert out["installed"] == 4
    assert out["enabled"] == 3
    assert out["disabled"] == 1
    assert out["marketplaces"]["mkt1"] == {"enabled": 1, "total": 2}
    assert out["marketplaces"]["(local)"] == {"enabled": 1, "total": 1}
    assert "a@mkt1" in out["enabled_names"] and "b@mkt1" not in out["enabled_names"]


# --- wave 3: gh / actions / registries / topology / fork / homebrew ---------


def test_parse_workflow_actions_and_claude():
    """`uses:` refs are collected (sha stripped, local ./ ignored); a Claude action is flagged."""
    wf = ["jobs:\n  x:\n    steps:\n      - uses: actions/checkout@abc123\n"
          "      - uses: ./local-action\n      - uses: anthropics/claude-code-action@v1"]
    out = ed.parse_workflow_actions(wf)
    assert "actions/checkout" in out["actions"]
    assert "./local-action" not in out["actions"]
    assert out["claude_action"] is True
    assert ed.parse_workflow_actions(["- uses: actions/setup-uv@v1"])["claude_action"] is False


def test_parse_workflow_platforms():
    """runs-on + matrix os arrays normalize to linux/macos/windows."""
    wf = ["runs-on: ubuntu-latest\nstrategy:\n  matrix:\n    os: [macos-latest, windows-latest]"]
    assert ed.parse_workflow_platforms(wf) == ["linux", "macos", "windows"]


def test_parse_gh_auth():
    """gh auth status → username + scopes + working; token is never captured."""
    text = ("github.com\n  ✓ Logged in to github.com account Emasoft\n"
            "  - Token: gho_XXXX\n  - Token scopes: 'gist', 'repo', 'workflow'")
    out = ed.parse_gh_auth(text)
    assert out["username"] == "Emasoft"
    assert out["working"] is True
    assert out["scopes"] == ["gist", "repo", "workflow"]
    assert "gho_XXXX" not in json.dumps(out)


def test_parse_active_gh_user():
    """The active user is read from a hosts.yml `user:` line."""
    assert ed.parse_active_gh_user("github.com:\n    user: Emasoft\n") == "Emasoft"
    assert ed.parse_active_gh_user("") == ""


def test_project_name_from_manifest():
    """The package name comes from pyproject, else package.json, else Cargo."""
    assert ed.project_name_from_manifest(pyproject='[project]\nname = "my-pkg"\n') == "my-pkg"
    assert ed.project_name_from_manifest(package_json='{"name": "js-pkg"}') == "js-pkg"
    assert ed.project_name_from_manifest(cargo='[package]\nname = "rs-pkg"\n') == "rs-pkg"
    assert ed.project_name_from_manifest() is None


def test_classify_repo_topology():
    """A workspace or nested git → mono-repo/multi-git; multiple languages → mixed."""
    single = ed.classify_repo_topology(languages=["python"], nested_git_count=0,
                                       has_submodules=False, workspaces=[], repo_symlinks=[])
    assert single["structure"] == "single-project" and single["git"] == "single-git"
    assert single["mixed_language"] is False

    mono = ed.classify_repo_topology(languages=["python", "rust"], nested_git_count=2,
                                     has_submodules=True, workspaces=["cargo-workspace"],
                                     repo_symlinks=[])
    assert mono["structure"] == "mono-repo" and mono["git"] == "multi-git"
    assert mono["mixed_language"] is True and mono["nested_repos"] == 2


def test_summarize_fork():
    """isFork + parent → upstream slug; an `upstream` remote alone also marks a fork."""
    gh = {"isFork": True, "parent": {"nameWithOwner": "Owner/Upstream"}}
    assert ed.summarize_fork(gh) == {"is_fork": True, "upstream": "Owner/Upstream"}
    by_remote = ed.summarize_fork({}, upstream_remote="git@github.com:Up/Stream.git")
    assert by_remote["is_fork"] is True and by_remote["upstream"] == "Up/Stream"
    assert ed.summarize_fork({"isFork": False}) == {"is_fork": False, "upstream": ""}


def test_homebrew_tap_status():
    """A homebrew-* name or a Formula/ dir → a tap with the Tap-Trust note; else None."""
    by_name = ed.homebrew_tap_status("user/homebrew-tools", has_formula_dir=False)
    assert by_name is not None and by_name["is_tap"] is True and "brew trust" in by_name["note"]
    by_dir = ed.homebrew_tap_status("user/whatever", has_formula_dir=True)
    assert by_dir is not None and by_dir["is_tap"] is True
    assert ed.homebrew_tap_status("user/normal-repo", has_formula_dir=False) is None
