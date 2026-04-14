# satdeploy demo — zero-prerequisite push + rollback in 4 commands
#
# Flow:
#   1. satdeploy status         (baseline — test_app v1.0.0 deployed, git-tagged)
#   2. satdeploy push test_app  (deploys v2 — new hash, new git commit)
#   3. satdeploy rollback test_app  (undoes in one command)
#   4. satdeploy status         (proof — back to v1 hash, original git commit)
#
# No Docker. No shell hops. No satellite simulator. Just the real product
# code against a local throwaway git repo + target directory.
#
# Render:
#   ROD_BROWSER_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" vhs demo/demo.tape

Output demo/demo.gif

Set Shell        "zsh"
Set FontSize     14
Set Width        1400
Set Height       600
Set Theme        "Catppuccin Mocha"
Set TypingSpeed  45ms
Set Padding      20

# ── Reset any prior demo state ─────────────────────────────────
Type "satdeploy demo stop --clean 2>/dev/null >/dev/null; clear"
Sleep 300ms
Enter
Sleep 500ms

# ── Set up the demo (fast: just a git repo + a target dir) ─────
Type "satdeploy demo start"
Sleep 300ms
Enter
Sleep 2s

# ── Baseline: test_app v1.0.0 is deployed, git-tagged ──────────
Type "satdeploy status"
Sleep 300ms
Enter
Sleep 2500ms

# ── Push v2 from the same working tree — new hash, new commit ──
Type "satdeploy push test_app"
Sleep 300ms
Enter
Sleep 2s

# ── Rollback in one command ────────────────────────────────────
Type "satdeploy rollback test_app"
Sleep 300ms
Enter
Sleep 2s

# ── Proof: status now shows the original hash AND git commit ───
Type "satdeploy status"
Sleep 300ms
Enter
Sleep 3s

Sleep 2s
