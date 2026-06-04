"""Tests for scripts/lib/prototype_pollution_modern_patterns.py.

2 tests per rule (1 positive + 1 negative), plus data-model sanity checks.
Targets 8 prototype-pollution rules (Wave-32 distill-round-18).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import prototype_pollution_modern_patterns as pp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must expose all 8 documented rule IDs."""
    assert isinstance(pp.RULES, tuple)
    rule_ids = {r.id for r in pp.RULES}
    expected = {
        "pp-lodash-merge-req",
        "pp-qs-allow-prototypes",
        "pp-orm-constructor-req-body",
        "pp-hasownproperty-on-untrusted",
        "pp-object-assign-this-options",
        "pp-third-party-deep-merge",
        "pp-set-prototype-of-external",
        "pp-loop-bracket-assign",
    }
    assert expected == rule_ids
    assert len(pp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in pp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = pp.Finding(
        rule_id="pp-test",
        line=1,
        column=2,
        matched_text="x",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "pp-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert pp.scan_text("") == []


# ---------- Helper -------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[pp.Finding]:
    """Return findings matching the given rule_id."""
    return [f for f in pp.scan_text(text) if f.rule_id == rule_id]


# ---------- PP-01 : pp-lodash-merge-req ----------------------------------


def test_pp01_lodash_defaultsdeep_req_body_flags() -> None:
    """_.defaultsDeep with req.body argument triggers HIGH finding."""
    src = "const config = _.defaultsDeep({}, req.body, defaults);\n"
    hits = _hits("pp-lodash-merge-req", src)
    assert hits, "expected a finding for _.defaultsDeep(req.body)"
    assert hits[0].severity == "HIGH"


def test_pp01_lodash_merge_static_object_silent() -> None:
    """_.merge with only static objects (no req.*) is silent."""
    src = "const result = _.merge({}, defaultConfig, userConfig);\n"
    assert not _hits("pp-lodash-merge-req", src), "no req.* — should be silent"


# ---------- PP-02 : pp-qs-allow-prototypes -------------------------------


def test_pp02_qs_parse_allow_prototypes_true_flags() -> None:
    """qs.parse with allowPrototypes:true triggers HIGH finding."""
    src = "const parsed = qs.parse(req.rawQuery, { allowPrototypes: true });\n"
    hits = _hits("pp-qs-allow-prototypes", src)
    assert hits, "expected a finding for allowPrototypes:true"
    assert hits[0].severity == "HIGH"


def test_pp02_qs_parse_no_allow_prototypes_silent() -> None:
    """qs.parse without allowPrototypes option is silent."""
    src = "const parsed = qs.parse(req.rawQuery, { depth: 5 });\n"
    assert not _hits("pp-qs-allow-prototypes", src)


# ---------- PP-03 : pp-orm-constructor-req-body --------------------------


def test_pp03_mongoose_new_model_req_body_flags() -> None:
    """new Model(req.body) triggers HIGH finding — mongoose mass-assign."""
    src = "const user = new User(req.body);\n"
    hits = _hits("pp-orm-constructor-req-body", src)
    assert hits, "expected a finding for new User(req.body)"
    assert hits[0].severity == "HIGH"


def test_pp03_orm_create_validated_object_silent() -> None:
    """Model.create with a pre-validated DTO variable is silent."""
    src = "const user = await User.create(validatedDto);\n"
    assert not _hits("pp-orm-constructor-req-body", src)


# ---------- PP-04 : pp-hasownproperty-on-untrusted -----------------------


def test_pp04_req_body_hasownproperty_flags() -> None:
    """req.body.hasOwnProperty(key) triggers MEDIUM finding."""
    src = "if (req.body.hasOwnProperty(key)) { target[key] = req.body[key]; }\n"
    hits = _hits("pp-hasownproperty-on-untrusted", src)
    assert hits, "expected a finding for req.body.hasOwnProperty"
    assert hits[0].severity == "MEDIUM"


def test_pp04_safe_object_hasown_silent() -> None:
    """Object.hasOwn(obj, key) is the safe form — must be silent."""
    src = "if (Object.hasOwn(req.body, key)) { target[key] = req.body[key]; }\n"
    assert not _hits("pp-hasownproperty-on-untrusted", src)


# ---------- PP-05 : pp-object-assign-this-options ------------------------


def test_pp05_object_assign_this_options_flags() -> None:
    """Object.assign(this, options) in a constructor triggers MEDIUM finding."""
    src = (
        "class Plugin {\n"
        "  constructor(options) {\n"
        "    Object.assign(this, options);\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("pp-object-assign-this-options", src)
    assert hits, "expected a finding for Object.assign(this, options)"
    assert hits[0].severity == "MEDIUM"


def test_pp05_object_assign_different_target_silent() -> None:
    """Object.assign to a non-this target is silent for this rule."""
    src = "const merged = Object.assign({}, defaults, options);\n"
    assert not _hits("pp-object-assign-this-options", src)


# ---------- PP-06 : pp-third-party-deep-merge ----------------------------


def test_pp06_require_merge_deep_flags() -> None:
    """require('merge-deep') triggers HIGH finding."""
    src = "const merge = require('merge-deep');\n"
    hits = _hits("pp-third-party-deep-merge", src)
    assert hits, "expected a finding for require('merge-deep')"
    assert hits[0].severity == "HIGH"


def test_pp06_require_lodash_clone_silent() -> None:
    """require('lodash/cloneDeep') is not a flagged deep-merge package."""
    src = "const cloneDeep = require('lodash/cloneDeep');\n"
    assert not _hits("pp-third-party-deep-merge", src)


# ---------- PP-07 : pp-set-prototype-of-external -------------------------


def test_pp07_setprototypeof_with_proto_prop_flags() -> None:
    """Object.setPrototypeOf(config, incoming.__proto__) triggers HIGH."""
    src = "Object.setPrototypeOf(config, incoming.__proto__ || incoming);\n"
    hits = _hits("pp-set-prototype-of-external", src)
    assert hits, "expected a finding for setPrototypeOf with .__proto__"
    assert hits[0].severity == "HIGH"


def test_pp07_setprototypeof_with_known_safe_proto_silent() -> None:
    """Object.setPrototypeOf resetting to Object.prototype is silent."""
    src = "Object.setPrototypeOf(obj, Object.prototype);\n"
    assert not _hits("pp-set-prototype-of-external", src)


# ---------- PP-08 : pp-loop-bracket-assign -------------------------------


def test_pp08_object_entries_req_body_foreach_flags() -> None:
    """Object.entries(req.body).forEach triggers HIGH finding."""
    src = "Object.entries(req.body).forEach(([k, v]) => { this[k] = v; });\n"
    hits = _hits("pp-loop-bracket-assign", src)
    assert hits, "expected a finding for Object.entries(req.body).forEach"
    assert hits[0].severity == "HIGH"


def test_pp08_object_entries_static_obj_silent() -> None:
    """Object.entries on a static config object (no req.*) is silent."""
    src = "Object.entries(defaultConfig).forEach(([k, v]) => { this[k] = v; });\n"
    assert not _hits("pp-loop-bracket-assign", src)
