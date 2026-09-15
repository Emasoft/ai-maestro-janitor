# Close the claim — keyed, fresh-shell-safe

`complete` runs in a fresh shell where `$CLAIM_ID`/`$REPORT_FILE` are empty (shell
variables set in an earlier Bash call do not survive into a new one). Record the
report path with `set-report`, keyed by chore+scope, then close with the same key:

```bash
DC="$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py"
A=(--state-dir "$STATE_DIR" --chore consolidate --scope "$SCOPE")
uv run --script --quiet "$DC" set-report "${A[@]}" "$REPORT_FILE"
uv run --script --quiet "$DC" complete "${A[@]}"
```
