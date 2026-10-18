# Close the claim — keyed, fresh-shell-safe

`set-report` runs in the SAME Bash call that just wrote `$REPORT_FILE` (its vars are still
alive here). `complete` runs later with STATE_DIR RETYPED as the literal path from the spawn
prompt, and only adds `--chore split --scope <literal scope from the claim step's output>` if
it exits 2 saying more than one claim is current:

The two commands (`set-report`, then `complete`) are in the report-closing step of this
chore's SKILL.md, where `${CLAUDE_PLUGIN_ROOT}` is already resolved to the absolute plugin
path. Run them exactly as written there. This file is read from disk, so a plugin-root
variable written here would stay literal (TRDD-JQLBZMMN).
