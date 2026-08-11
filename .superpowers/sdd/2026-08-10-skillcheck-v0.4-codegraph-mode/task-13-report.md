# Task 13: v0.4 diagnostics and uninstall

- Doctor now emits only the 12 v0.4 diagnostics and limits repairs to an empty catalog or Skillcheck-owned MCP/marker integration.
- Uninstall defaults to removing only Skillcheck integration entries and marker blocks; `--complete`, `--keep-cli`, and `--keep-data` control broader owned-state removal.
- Agent discovery ignores empty adapters, and the CLI can build a real safe uninstall context.

Verification: targeted lifecycle/command tests passed; Ruff and `git diff --check` passed.
