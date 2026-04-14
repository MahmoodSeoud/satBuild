# satdeploy demo - deploy, verify, roll back.
#
# Render:
#   vhs demo/demo.tape

Output demo/demo.gif

Set Shell        "zsh"
Set FontSize     14
Set Width        1400
Set Height       600
Set Theme        { "name": "ground-station", "background": "#0b0f17", "foreground": "#e6e6e6", "cursor": "#7dd3fc", "selection": "#1e293b", "black": "#1a1f2e", "red": "#fca5a5", "green": "#86efac", "yellow": "#fde68a", "blue": "#93c5fd", "magenta": "#c4b5fd", "cyan": "#7dd3fc", "white": "#d1d5db", "brightBlack": "#7d8799", "brightRed": "#fecaca", "brightGreen": "#bbf7d0", "brightYellow": "#fef3c7", "brightBlue": "#bfdbfe", "brightMagenta": "#ddd6fe", "brightCyan": "#a5e8fd", "brightWhite": "#f3f4f6" }
Set TypingSpeed  35ms
Set Padding      20

Hide
Type `export PS1=$'\n%F{244}$%f '`
Enter
Type `export PATH="$HOME/.satdeploy/demo/target/bin:$PATH"`
Enter
Type "satdeploy demo stop --clean 2>/dev/null >/dev/null"
Enter
Type "satdeploy demo start >/dev/null 2>&1"
Enter
Type "clear"
Enter
Sleep 400ms
Show

Type "test_app"
Sleep 300ms
Enter
Sleep 2500ms

Type "satdeploy push test_app"
Sleep 300ms
Enter
Sleep 3500ms

Type "test_app"
Sleep 300ms
Enter
Sleep 3000ms

Type "satdeploy rollback test_app"
Sleep 300ms
Enter
Sleep 3000ms

Type "test_app"
Sleep 300ms
Enter
Sleep 4500ms

Hide
Type "satdeploy demo stop --clean >/dev/null 2>&1"
Enter
Show
