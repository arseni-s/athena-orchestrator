"""One orchestrator per repository (athena-orchestrator, docs/MODEL.md section 3.3).

Two orchestrators in one repo would claim the same package, deploy to test over each
other's checks, and conflict on the plan file. The orchestrate skill therefore runs

    python athena_lock.py claim            at session start
    python athena_lock.py release          at session end
    python athena_lock.py status
    python athena_lock.py release --force  the user only: free a lock left behind

`claim` exits 0 when this session holds the lock (taken, renewed, or taken over from a
holder that is gone), 1 when another live orchestrator holds it, and 2 when it cannot
tell (no git repo, a lock file it cannot read or write). 1 and 2 both mean: stop.

The lock is one file in the git common directory, so the main checkout and every package
worktree share it. It names the holder by the Claude process (CLAUDE_PID) and the session
(CLAUDE_CODE_SESSION_ID), both set by Claude Code for every command it runs. A holder
whose process has ended no longer counts, so a crashed session frees the lock by itself;
the same process (after /clear, say) takes it back. A holder with no known process counts
as live: only the user frees that one. It fails closed: when in doubt, it refuses.

Standard library only; runs on Windows and POSIX.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import subprocess
import sys
import time

NAME = "athena-orchestrator.lock"


class LockError(Exception):
    """The lock cannot be checked: the caller must stop."""


def lock_path(start: str) -> str:
    """The lock file in the git common directory of the repo at `start`."""
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LockError(f"git cannot run ({exc})") from exc
    common = out.stdout.strip()
    if out.returncode != 0 or not common:
        raise LockError(f"{start} is not in a git repository")
    return os.path.join(os.path.normpath(os.path.join(start, common)), NAME)


def alive(pid: object) -> bool | None:
    """Whether a process runs: True, False, or None when it cannot be told."""
    try:
        pid = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


@contextlib.contextmanager
def _mutex(path: str):
    """A short lock around read-check-write. One left by a crash is broken after 10 s."""
    mutex, start = path + ".mutex", time.time()
    while True:
        try:
            os.close(os.open(mutex, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(mutex) > 10:
                    os.remove(mutex)
                    continue
            except OSError:
                pass
            if time.time() - start > 5:
                raise LockError(f"{mutex} is held by another process; try again")
            time.sleep(0.05)
        except OSError as exc:
            raise LockError(f"cannot create {mutex} ({exc})") from exc
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.remove(mutex)


def _read(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    for _ in range(5):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise LockError(f"{path} is not a lock record")
            return data
        except PermissionError:
            time.sleep(0.05)  # being replaced (Windows)
        except (OSError, ValueError) as exc:
            raise LockError(f"{path} cannot be read ({exc})") from exc
    raise LockError(f"{path} cannot be read")


def _write(path: str, data: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1)
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)  # a reader has it open (Windows)
    with contextlib.suppress(OSError):
        os.remove(tmp)
    raise LockError(f"cannot write {path}")


def _same(holder: dict, session: str | None, pid: str | None) -> bool:
    return bool((pid and holder.get("pid") == pid) or (session and holder.get("session") == session))


def gone(holder: dict) -> bool:
    """A holder whose Claude process has ended. Unknown counts as live."""
    return alive(holder.get("pid")) is False


def claim(path: str, session: str | None, pid: str | None) -> tuple[bool, dict]:
    """(True, the new record) or (False, the other live holder)."""
    with _mutex(path):
        holder = _read(path)
        if holder and not _same(holder, session, pid) and not gone(holder):
            return False, holder
        record = {"session": session, "pid": pid, "since": _now()}
        if holder and _same(holder, session, pid):
            record["since"] = holder.get("since") or record["since"]
        elif holder:
            record["took_over"] = {k: holder.get(k) for k in ("session", "pid", "since")}
        _write(path, record)
        return True, record


def release(path: str, session: str | None, pid: str | None, force: bool = False) -> str:
    """'released', 'free' (no lock), or 'not yours' (another holder; not forced)."""
    with _mutex(path):
        holder = _read(path)
        if not holder:
            return "free"
        if not force and not _same(holder, session, pid):
            return "not yours"
        os.remove(path)
        return "released"


def describe(holder: dict) -> str:
    session = (holder.get("session") or "unknown")[:8]
    return f"session {session}, Claude process {holder.get('pid') or 'unknown'}, since {holder.get('since', '?')}"


def main(argv: list[str]) -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    actions = {"claim", "release", "status"}
    if not argv or argv[0] not in actions or [a for a in argv[1:] if a != "--force"] \
            or ("--force" in argv and argv[0] != "release"):
        print("usage: athena_lock.py claim | status | release [--force]", file=sys.stderr)
        return 64
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    pid = os.environ.get("CLAUDE_PID") or None
    try:
        path = lock_path(os.getcwd())
        if argv[0] == "status":
            holder = _read(path)
            if not holder:
                print("free: no orchestrator holds this repository")
            else:
                state = "left behind (its Claude process has ended)" if gone(holder) else "held"
                mine = " (this session)" if _same(holder, session, pid) else ""
                print(f"{state}{mine}: {describe(holder)}")
            return 0
        if argv[0] == "release":
            result = release(path, session, pid, force="--force" in argv)
            if result == "not yours":
                print(f"not released: another orchestrator holds it ({describe(_read(path) or {})}). "
                      "Only the user frees another session's lock, with --force.")
                return 1
            print(result)
            return 0
        ok, holder = claim(path, session, pid)
    except LockError as exc:
        print(f"ORCHESTRATOR LOCK: cannot check it: {exc}. Stop, and tell the user.")
        return 2
    if ok:
        note = ""
        if holder.get("took_over"):
            note = f"; took over from {describe(holder['took_over'])}, whose Claude process has ended"
        if not pid:
            note += ("; CLAUDE_PID is not set, so this lock cannot expire by itself: release it at "
                     "the end of the session")
        print(f"held by this session ({describe(holder)}){note}")
        return 0
    print("ORCHESTRATOR LOCK: another orchestrator is running in this repository "
          f"({describe(holder)}). Only one runs per repo (docs/MODEL.md section 3.3 of "
          "athena-orchestrator): two would claim the same package and deploy over each other. "
          "Stop, and tell the user to finish or close that session first. If that session is "
          "gone and the lock was left behind, only the user frees it: "
          "`athena_lock.py release --force`.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
