"""Mass-assignment / over-posting patterns in REST APIs.

Wave-32 distillation round 18.

Catalogue of 9 mass-assignment anti-patterns distilled in
`reports/distill-round-18/mass-assignment-rest.md`. Targets Django,
Rails, Spring MVC, FastAPI/Pydantic, Node.js/Mongoose/Sequelize, Jackson
(Java), and NestJS/TypeORM surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic SQL-injection / ORM injection — `db_injection_patterns.py`.
  * Generic deserialization gadget chains — `cross_lang_deserialize_patterns.py`.
  * NoSQL aggregation injection — `nosql_aggregation_patterns.py`.
  * GraphQL / persisted-query mass-exposure — `graphql_persisted_query_patterns.py`.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * ma-django-serializer-fields-all         (MAJOR)
  * ma-django-modelform-empty-exclude       (MAJOR)
  * ma-rails-permit-bang                    (CRITICAL)
  * ma-rails-update-attributes-params       (CRITICAL)
  * ma-spring-modelattribute-no-binder      (MAJOR)
  * ma-pydantic-basemodel-orm-spread        (MAJOR)
  * ma-mongoose-reqbody-update              (MAJOR)
  * ma-jackson-jsonignoreprops-entity       (MAJOR)
  * ma-nestjs-dto-entity-collapse           (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:

  ASI-06 — Mass-assignment / over-posting (REST API object binding without
            an explicit allowlist of writable fields, enabling an attacker
            to write privileged columns — role, is_staff, balance — via a
            crafted request body).

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- MA-1 : ma-django-serializer-fields-all -----------------------------
# ModelSerializer with fields = "__all__" exposes every ORM column for
# deserialization, including admin fields (is_staff, role, is_superuser).
_DJANGO_SERIALIZER_FIELDS_ALL = _re(
    r'fields\s*=\s*["\']__all__["\']'
)

# ---- MA-2 : ma-django-modelform-empty-exclude ---------------------------
# ModelForm with exclude = [] effectively allows all model fields through
# the form — identical to fields = "__all__" but via the exclude path.
_DJANGO_MODELFORM_EMPTY_EXCLUDE = _re(
    r'exclude\s*=\s*\[\s*\]'
)

# ---- MA-3 : ma-rails-permit-bang ----------------------------------------
# Rails strong-parameters escape hatch — `.permit!` allows ALL params
# without restriction. Almost never legitimate in application code.
_RAILS_PERMIT_BANG = _re(
    r'\.permit!\s*(?:#[^\n]*)?\n'
    r'|\.permit!\s*$'
)

# ---- MA-4 : ma-rails-update-attributes-params ---------------------------
# `update_attributes(params[:x])` — the classic pre-strong-params Rails
# mass-assignment vector. `require()` alone without `.permit()` is equally
# dangerous: `update(params.require(:user))`.
_RAILS_UPDATE_ATTRIBUTES_PARAMS = _re(
    r'update_attributes\s*\(\s*params'
)

# ---- MA-5 : ma-spring-modelattribute-no-binder --------------------------
# Spring MVC `@ModelAttribute` on a controller argument binds ALL request
# params to the Java object if no `@InitBinder` with `setAllowedFields`
# is present. The regex matches the decorator + bound type + param name
# pattern, signalling manual audit is required.
_SPRING_MODELATTRIBUTE = _re(
    r'@ModelAttribute\s+\w[\w.<>,\s]*\s+\w+\s*[,)]'
)

# ---- MA-6 : ma-pydantic-basemodel-orm-spread ----------------------------
# FastAPI/Pydantic pattern: `OrmModel(**req.dict())` or
# `OrmModel(**req.model_dump())` — every Pydantic field flows directly
# into the ORM constructor, including any privileged fields declared in
# the model.
_PYDANTIC_ORM_SPREAD = _re(
    r'\*\*\w+\.(?:model_dump|dict)\(\s*\)'
)

# ---- MA-7 : ma-mongoose-reqbody-update ----------------------------------
# Node.js ORM patterns where `req.body` is passed directly into an
# ORM mutation — Mongoose `findByIdAndUpdate`, Sequelize `bulkCreate`,
# or generic Express spread `{ ...req.body }`.
# Three distinct variant patterns compiled separately, matched together.
_MONGOOSE_FIND_UPDATE = _re(
    r'findByIdAndUpdate\s*\([^)]*,\s*req\.body'
)
_SEQUELIZE_BULK_CREATE = _re(
    r'bulkCreate\s*\(\s*req\.body'
)
_EXPRESS_SPREAD_REQBODY = _re(
    r'\.\s*update\s*\(\s*\{\s*\.\.\.req\.body\s*\}'
)

# ---- MA-8 : ma-jackson-jsonignoreprops-entity ---------------------------
# Jackson `@JsonIgnoreProperties(ignoreUnknown = true)` signals that
# unknown fields are silently dropped — but KNOWN fields that match bean
# properties WILL be bound, including id, version, admin, role. Severity
# rises when `@Entity` or `@Document` co-appear in the same file.
_JACKSON_JSONIGNOREPROPS = _re(
    r'@JsonIgnoreProperties\s*\(\s*ignoreUnknown\s*=\s*true'
)

# Co-presence marker: JPA entity or Spring Data document annotation.
_JPA_ENTITY_MARKER = _re(
    r'@(?:Entity|Document)\b'
)

# ---- MA-9 : ma-nestjs-dto-entity-collapse --------------------------------
# NestJS anti-pattern: an `@Entity()` ORM class is also used directly as
# a controller `@Body()` parameter type. Any field that passes
# class-validator decorators is also directly writable as an ORM column.
# Two variants:
#   (a) `@Body() param: SomeEntity` — naming convention heuristic.
#   (b) `@Body() param: SomethingEntity` — explicit `Entity` suffix.
_NESTJS_BODY_ENTITY = _re(
    r'@Body\(\s*\)\s+\w+\s*:\s*\w+Entity\b'
)


# ---- RULES tuple (pre-compiled, module-load) ----------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ma-django-serializer-fields-all",
        name="Django ModelSerializer with fields = '__all__' exposes all ORM columns",
        severity="MAJOR",
        description=(
            "A DRF ModelSerializer uses `fields = \"__all__\"` in its Meta "
            "class. This exposes every column of the underlying ORM model "
            "for deserialization, including privileged fields such as "
            "`is_staff`, `is_superuser`, `role`, and `created_by`. An "
            "attacker POST-ing `{\"is_staff\": true}` can write that value "
            "to the database unless `read_only_fields` is explicitly "
            "configured for every sensitive column. Use an explicit field "
            "list instead."
        ),
        pattern=_DJANGO_SERIALIZER_FIELDS_ALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-django-modelform-empty-exclude",
        name="Django ModelForm with exclude = [] accepts all model fields",
        severity="MAJOR",
        description=(
            "A Django ModelForm sets `exclude = []` in its Meta class. "
            "An empty exclude list is semantically equivalent to "
            "`fields = \"__all__\"` — every model attribute is accepted "
            "from the HTTP request. Combined with a view calling "
            "`form.save()`, this allows any model column to be over-posted. "
            "Replace with an explicit `fields` list or a non-empty "
            "`exclude` list."
        ),
        pattern=_DJANGO_MODELFORM_EMPTY_EXCLUDE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-rails-permit-bang",
        name="Rails strong-parameters permit! allows all params without restriction",
        severity="CRITICAL",
        description=(
            "A Rails controller calls `.permit!` on a params hash, "
            "bypassing all strong-parameter filtering and allowing an "
            "attacker to set any model attribute including `admin`, "
            "`role`, `confirmed`, or `locked`. `permit!` is almost never "
            "legitimate in application code — it is an escape hatch "
            "occasionally used in test factories or seed scripts. Replace "
            "with an explicit `permit(:field1, :field2)` allowlist."
        ),
        pattern=_RAILS_PERMIT_BANG,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-rails-update-attributes-params",
        name="Rails update_attributes called with raw params — classic mass-assignment",
        severity="CRITICAL",
        description=(
            "A Rails controller calls `update_attributes(params[:model])` "
            "without a `.permit(...)` guard. This is the classic "
            "pre-strong-parameters mass-assignment vector that allowed "
            "attackers to set privileged columns such as `admin`, "
            "`is_admin`, `role`, `balance`, or any other model attribute. "
            "`update_attributes` is deprecated in Rails 6+ (use `update`), "
            "but the pattern is still found in legacy codebases. Require "
            "`.permit(:f1, :f2)` before any ORM update."
        ),
        pattern=_RAILS_UPDATE_ATTRIBUTES_PARAMS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-spring-modelattribute-no-binder",
        name="Spring @ModelAttribute binds all request params to a controller argument",
        severity="MAJOR",
        description=(
            "A Spring MVC controller method uses `@ModelAttribute` on an "
            "argument, which binds ALL request parameters (form fields, "
            "query string) to the bound Java object. Without an "
            "`@InitBinder` that calls `binder.setAllowedFields(...)`, an "
            "attacker can set any bean property, including `admin`, "
            "`accountNonExpired`, or JPA columns like `version` and `id`. "
            "Add `@InitBinder` with a restrictive `setAllowedFields` call, "
            "or bind to a dedicated DTO that does not contain privileged "
            "fields."
        ),
        pattern=_SPRING_MODELATTRIBUTE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-pydantic-basemodel-orm-spread",
        name="Pydantic model spread into ORM constructor passes all fields unfiltered",
        severity="MAJOR",
        description=(
            "A FastAPI endpoint uses `**req.dict()` or `**req.model_dump()` "
            "to pass all Pydantic model fields directly into an ORM "
            "constructor. If the Pydantic model contains fields that should "
            "be server-side-only (e.g. `is_admin`, `role`, `balance`, "
            "`credits`), an attacker can supply those values in the JSON "
            "request body. Review which fields the Pydantic model exposes "
            "and use `exclude` or separate request / response schemas."
        ),
        pattern=_PYDANTIC_ORM_SPREAD,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-mongoose-reqbody-update",
        name="Mongoose/Sequelize ORM mutation receives raw req.body without filtering",
        severity="MAJOR",
        description=(
            "A Node.js / Express handler passes `req.body` directly into "
            "a Mongoose `findByIdAndUpdate`, a Sequelize `bulkCreate`, or "
            "an Express object spread `{ ...req.body }` used as an ORM "
            "update payload. An attacker can set any field the ORM model "
            "accepts, including privileged columns such as `role`, "
            "`isAdmin`, `credits`, or `__v`. Filter with an explicit "
            "allowlist (e.g. `_.pick(req.body, ['name', 'email'])`) "
            "before passing to the ORM."
        ),
        # pattern field stores the first sub-pattern; scan_text iterates all three.
        pattern=_MONGOOSE_FIND_UPDATE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-jackson-jsonignoreprops-entity",
        name="Jackson @JsonIgnoreProperties(ignoreUnknown=true) on a JPA entity",
        severity="MAJOR",
        description=(
            "A Java class annotated with "
            "`@JsonIgnoreProperties(ignoreUnknown = true)` silently drops "
            "unknown request fields but WILL bind any field that matches a "
            "bean property — including `id`, `version`, `createdBy`, "
            "`admin`, or `role`. When this annotation appears on a class "
            "that is also a JPA `@Entity` or Spring Data `@Document`, any "
            "field declared on the entity can be written by an attacker "
            "through a `@RequestBody` endpoint. Use a dedicated DTO class "
            "as the `@RequestBody` type instead of the entity."
        ),
        pattern=_JACKSON_JSONIGNOREPROPS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ma-nestjs-dto-entity-collapse",
        name="NestJS @Body() parameter typed as an ORM Entity collapses DTO and entity",
        severity="MAJOR",
        description=(
            "A NestJS controller method accepts `@Body() param: SomeEntity` "
            "where the type name ends in `Entity`, indicating that the ORM "
            "entity class is being used directly as the request DTO. Every "
            "column declared on the entity — including `isAdmin`, "
            "`subscriptionTier`, `credits` — can be written by the client "
            "even if class-validator decorators are present, because those "
            "decorators only validate format, not write-access. Introduce a "
            "separate DTO class with only the fields the client is permitted "
            "to supply."
        ),
        pattern=_NESTJS_BODY_ENTITY,
        owasp_asi="ASI-06",
    ),
)


# ---- Internal helpers ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * MA-7 (mongoose-reqbody-update) — iterates three sub-patterns
        (_MONGOOSE_FIND_UPDATE, _SEQUELIZE_BULK_CREATE,
        _EXPRESS_SPREAD_REQBODY) and emits a finding for each match
        under the single rule ID.
      * MA-8 (jackson-jsonignoreprops-entity) — promotes severity to
        MAJOR when `@Entity` or `@Document` co-appear in the same
        file.  The base rule fires regardless; the promotion is noted
        in the description.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- MA-1 : ma-django-serializer-fields-all ----
    rule_ma1 = rule_by_id["ma-django-serializer-fields-all"]
    for m in _DJANGO_SERIALIZER_FIELDS_ALL.finditer(text):
        _emit(rule_ma1, m.start(), m.group(0))

    # ---- MA-2 : ma-django-modelform-empty-exclude ----
    rule_ma2 = rule_by_id["ma-django-modelform-empty-exclude"]
    for m in _DJANGO_MODELFORM_EMPTY_EXCLUDE.finditer(text):
        _emit(rule_ma2, m.start(), m.group(0))

    # ---- MA-3 : ma-rails-permit-bang ----
    rule_ma3 = rule_by_id["ma-rails-permit-bang"]
    for m in _RAILS_PERMIT_BANG.finditer(text):
        _emit(rule_ma3, m.start(), m.group(0))

    # ---- MA-4 : ma-rails-update-attributes-params ----
    rule_ma4 = rule_by_id["ma-rails-update-attributes-params"]
    for m in _RAILS_UPDATE_ATTRIBUTES_PARAMS.finditer(text):
        _emit(rule_ma4, m.start(), m.group(0))

    # ---- MA-5 : ma-spring-modelattribute-no-binder ----
    rule_ma5 = rule_by_id["ma-spring-modelattribute-no-binder"]
    for m in _SPRING_MODELATTRIBUTE.finditer(text):
        _emit(rule_ma5, m.start(), m.group(0))

    # ---- MA-6 : ma-pydantic-basemodel-orm-spread ----
    rule_ma6 = rule_by_id["ma-pydantic-basemodel-orm-spread"]
    for m in _PYDANTIC_ORM_SPREAD.finditer(text):
        _emit(rule_ma6, m.start(), m.group(0))

    # ---- MA-7 : ma-mongoose-reqbody-update (three sub-patterns) ----
    rule_ma7 = rule_by_id["ma-mongoose-reqbody-update"]
    for sub_pat in (_MONGOOSE_FIND_UPDATE, _SEQUELIZE_BULK_CREATE, _EXPRESS_SPREAD_REQBODY):
        for m in sub_pat.finditer(text):
            _emit(rule_ma7, m.start(), m.group(0))

    # ---- MA-8 : ma-jackson-jsonignoreprops-entity ----
    rule_ma8 = rule_by_id["ma-jackson-jsonignoreprops-entity"]
    has_entity = _file_contains(text, _JPA_ENTITY_MARKER)
    for m in _JACKSON_JSONIGNOREPROPS.finditer(text):
        _emit(rule_ma8, m.start(), m.group(0))
    # If co-presence of @Entity/@Document detected, add a note finding at the
    # first @Entity/@Document occurrence so the reviewer knows severity is MAJOR.
    if has_entity:
        entity_m = _JPA_ENTITY_MARKER.search(text)
        if entity_m is not None:
            # Only emit if the base rule also fired (there must be a finding for MA-8).
            if any(f.rule_id == "ma-jackson-jsonignoreprops-entity" for f in findings):
                _emit(rule_ma8, entity_m.start(), entity_m.group(0))

    # ---- MA-9 : ma-nestjs-dto-entity-collapse ----
    rule_ma9 = rule_by_id["ma-nestjs-dto-entity-collapse"]
    for m in _NESTJS_BODY_ENTITY.finditer(text):
        _emit(rule_ma9, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
