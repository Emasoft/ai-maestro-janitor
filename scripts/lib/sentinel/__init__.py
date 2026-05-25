# Sentinel structural-rule tier for the janitor workflow auditor.
#
# Native Python port of the structural detection rules from the Sentinel
# GitHub-Actions scanner (Ruby reference). The regex-amenable rules live in
# scripts/lib/zizmor_patterns.py (RE2 RegexSet); the rules in this package
# need job/step/trigger context or absence checks that a RegexSet cannot
# express.
#
# model.py is the shared contract (Workflow model + guard helpers + Rule
# base + the canonical Finding). Each rules_*.py module exposes a module-level
# RULES list that scripts/doctor_classify.py collects and runs.
