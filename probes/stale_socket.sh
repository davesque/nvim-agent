#!/bin/sh
# Which ways of exiting leave a headless nvim's default socket behind?
#
# Every nvim, including a `nvim --headless -l` client, listens on
# $TMPDIR/nvim.$USER/*/nvim.<pid>.0. Starts a sleeping headless nvim, ends it
# in different ways, and reports whether its socket file is still there.
# Also checks that vim.fn.serverstop(vim.v.servername) removes it up front.
#
# Usage: sh probes/stale_socket.sh   (touches no running editor)
set -u
work="$HOME/agent-workspace/stale-socket-probe"
mkdir -p "$work"
dir="$TMPDIR/nvim.$USER"
echo 'vim.uv.sleep(1500)' > "$work/sleep.lua"
echo 'os.exit(124)' > "$work/exit.lua"
echo 'vim.fn.serverstop(vim.v.servername); os.exit(124)' > "$work/stop_exit.lua"

left() { ls -R "$dir" 2>/dev/null | grep -q "^nvim\.$1\.0" && echo "socket LEFT" || echo "socket removed"; }

nvim --clean --headless -l "$work/sleep.lua" & p=$!; wait $p; echo "normal exit:       $(left $p)"
nvim --clean --headless -l "$work/sleep.lua" 2>/dev/null & p=$!; sleep 0.5; kill -TERM $p; wait $p; echo "SIGTERM:           $(left $p)"
nvim --clean --headless -l "$work/sleep.lua" & p=$!; sleep 0.5; kill -KILL $p; wait $p 2>/dev/null; echo "SIGKILL:           $(left $p)"
nvim --clean --headless -l "$work/exit.lua" & p=$!; wait $p; echo "os.exit:           $(left $p)"
nvim --clean --headless -l "$work/stop_exit.lua" & p=$!; wait $p; echo "serverstop+exit:   $(left $p)"

# Remove the stale sockets this probe created (their owners are dead).
for s in "$dir"/*/nvim.*.0; do
  pid=$(basename "$s" | cut -d. -f2)
  kill -0 "$pid" 2>/dev/null || { rm -f "$s"; rmdir "$(dirname "$s")" 2>/dev/null; }
done
rm -rf "$work"
