#!/bin/sh
# Runs one gate script (scripts/<name>.py) with Python, passing the hook event through stdin.
# Exits non-zero when no Python is found or the script fails to start, so the hook command's
# fallback answers instead: the gates fail closed (hooks/hooks.json).
#
# Windows (Git Bash) tries `python` and the `py` launcher first, because `python3` there is
# often the Microsoft Store stub; POSIX tries `python3` first. One process per call: the
# script itself needs Python 3.11+ (`tomllib`) and fails, closed, on an older one.
here=$(dirname "$0")
case "$(uname -s 2>/dev/null)" in
  MINGW* | MSYS* | CYGWIN*) candidates="python py python3" ;;
  *) candidates="python3 python" ;;
esac
for py in $candidates; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" -B "$here/$1"
  fi
done
echo "athena-orchestrator: no Python found on PATH (need Python 3.11+)" >&2
exit 1
