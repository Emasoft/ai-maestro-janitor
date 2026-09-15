# Close the claim — keyed, fresh-shell-safe

`set-report` runs in the SAME Bash call that just wrote `$REPORT_FILE` (its vars are still
alive here). `complete` runs later with STATE_DIR RETYPED as the literal path from the spawn
prompt, and only adds `--chore split --scope <literal scope from the claim step's output>` if
it exits 2 saying more than one claim is current:

```bash
DC="$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py"
uv run --script --quiet "$DC" set-report --state-dir "$STATE_DIR" "$REPORT_FILE"
uv run --script --quiet "$DC" complete --state-dir "$STATE_DIR"
```
