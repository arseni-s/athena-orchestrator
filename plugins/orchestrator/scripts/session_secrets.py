"""The agent's development credentials, loaded at the start of each Claude Code session.

Each project has its own 1Password service account, which opens exactly one vault: the
project's development vault (MODEL.md section 12.3). Its token is kept in the operating
system's credential store, never in the repository, and it reaches the session like this:

- `.claude/session-secrets.json` in the project (committed, holds no secret) names the
  stored credential, the vault, and the `op://` reference behind each variable:

      {"credential": "claude-project-secrets/<project>", "vault": "<vault>",
       "export_service_account_token": true,
       "env": {"GH_TOKEN": "op://<vault>/<item id>/credential"}}

- At session start (no argument; the SessionStart hook in hooks/hooks.json) this script
  reads the token, checks that it opens exactly that vault, reads each reference, and
  appends `export NAME='value'` lines to `$CLAUDE_ENV_FILE`, so the session's commands
  have them. It prints variable names only, never a value, and it never blocks a session.
- Hooks do not see `$CLAUDE_ENV_FILE`, so the merge guard reads `GH_TOKEN` itself with
  `env_values()`.

Commands:
  python session_secrets.py setup [project dir] [--pause]
      Run by the user, once per project, in their own terminal (adopt opens one). Takes
      the service account token from the clipboard (or keeps the stored one), checks it
      opens exactly one vault, stores it, finds the agent's token items in that vault
      (API Credential items whose title names GitHub or Railway), and writes
      `.claude/session-secrets.json`. Names only on screen.
  python session_secrets.py check [project dir]
      Names only, as JSON: the config, whether a token is stored, the vaults it opens, and
      which variables would load. For adopt and for diagnosis.

Standard library only. The credential store is Windows Credential Manager; elsewhere the
token may come from `OP_SERVICE_ACCOUNT_TOKEN` in the environment.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

CONFIG = Path(".claude") / "session-secrets.json"
PREFIX = "claude-project-secrets/"
SAY = "[athena-orchestrator secrets]"
NAME_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OP_TIMEOUT_S = 15
OP_CMD: Optional[list[str]] = None  # tests put a fake `op` here; None: find the real one
# The agent's tokens: an API Credential item in the vault whose title has the keyword.
KNOWN_TOKENS = {"GH_TOKEN": "github", "RAILWAY_TOKEN": "railway"}


class Problem(Exception):
    """Something the user can fix; the message never holds a secret."""


# --- the credential store --------------------------------------------------------------------

def _advapi():  # Windows only
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    lib = ctypes.WinDLL("advapi32", use_last_error=True)
    lib.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    lib.CredReadW.restype = wintypes.BOOL
    lib.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    lib.CredWriteW.restype = wintypes.BOOL
    lib.CredFree.argtypes = [ctypes.c_void_p]
    lib.CredFree.restype = None
    return ctypes, lib, CREDENTIAL


GENERIC, PERSIST_LOCAL_MACHINE = 1, 2


def read_stored(name: str) -> Optional[str]:
    """The token stored under `name`, or None."""
    if os.name != "nt":
        return None
    ctypes, lib, CREDENTIAL = _advapi()
    ptr = ctypes.POINTER(CREDENTIAL)()
    if not lib.CredReadW(name, GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        cred = ptr.contents
        if not cred.CredentialBlob or not cred.CredentialBlobSize:
            return None
        return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-16-le")
    finally:
        lib.CredFree(ptr)


def write_stored(name: str, token: str) -> None:
    if os.name != "nt":
        raise Problem("storing a token is supported on Windows only (Credential Manager)")
    ctypes, lib, CREDENTIAL = _advapi()
    blob = token.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL(Type=GENERIC, TargetName=name, UserName="op-service-account",
                      CredentialBlobSize=len(blob), Persist=PERSIST_LOCAL_MACHINE,
                      CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    if not lib.CredWriteW(ctypes.byref(cred), 0):
        raise Problem(f"Windows did not store the token (error {ctypes.get_last_error()})")


def token_for(cfg: dict) -> Optional[str]:
    return read_stored(cfg["credential"]) or os.environ.get("OP_SERVICE_ACCOUNT_TOKEN") or None


# --- 1Password -------------------------------------------------------------------------------

def op_path() -> Optional[str]:
    """The 1Password CLI, also when this process's PATH predates its install."""
    found = shutil.which("op")
    if found:
        return found
    if os.name == "nt":
        for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "op.exe",
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "1Password CLI" / "op.exe"):
            if p.is_file():
                return str(p)
    return None


def _op(args: list[str], token: str, timeout: float = OP_TIMEOUT_S) -> str:
    """stdout of `op <args>` with the service account token; Problem on failure (never a value)."""
    op = OP_CMD or ([op_path()] if op_path() else None)
    if not op:
        raise Problem("the 1Password CLI (op) was not found")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OP_SESSION_")}
    env.update(OP_SERVICE_ACCOUNT_TOKEN=token, OP_CACHE="false")
    try:
        out = subprocess.run([*op, *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        raise Problem(f"`op {args[0]} {args[1] if len(args) > 1 else ''}` timed out") from None
    except OSError as exc:
        raise Problem(f"the 1Password CLI did not run ({exc})") from None
    if out.returncode != 0:
        first = (out.stderr.strip().splitlines() or ["(no message)"])[0][:200]
        raise Problem(f"1Password refused `op {args[0]} {args[1] if len(args) > 1 else ''}`: {first}")
    return out.stdout


def _op_json(args: list[str], token: str) -> list:
    try:
        data = json.loads(_op(args, token))
    except ValueError:
        raise Problem(f"`op {args[0]} {args[1]}` did not answer JSON") from None
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise Problem(f"`op {args[0]} {args[1]}` did not answer a list")
    return data


def vaults(token: str) -> list[str]:
    return [str(v.get("name", "?")) for v in _op_json(["vault", "list", "--format", "json"], token)]


def read_ref(ref: str, token: str, timeout: float = OP_TIMEOUT_S) -> str:
    value = _op(["read", "--no-newline", ref], token, timeout)
    if not value:
        raise Problem(f"{ref} is empty")
    return value


def find_tokens(vault: str, token: str) -> dict[str, str]:
    """{variable: op:// reference} for the agent's token items found in the vault."""
    items = _op_json(["item", "list", "--vault", vault, "--format", "json"], token)
    found = {}
    for var, word in KNOWN_TOKENS.items():
        hits = [i for i in items if i.get("category") == "API_CREDENTIAL"
                and word in str(i.get("title", "")).lower()]
        if len(hits) == 1:
            found[var] = f"op://{vault}/{hits[0]['id']}/credential"
    return found


# --- the config ------------------------------------------------------------------------------

def project_root(start: str, timeout: float = 10) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True,
                             text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path(start).resolve()


def default_credential(root: Path) -> str:
    return PREFIX + re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-").lower()


def load_config(root: Path) -> Optional[dict]:
    """The project's config, checked; None when the project has none."""
    path = root / CONFIG
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Problem(f"{CONFIG} cannot be read ({exc})") from None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("credential"), str) \
            or not isinstance(cfg.get("vault"), str) or not isinstance(cfg.get("env", {}), dict):
        raise Problem(f"{CONFIG} needs \"credential\" and \"vault\" (strings) and an \"env\" object")
    bad = [n for n in cfg.get("env", {}) if not NAME_OK.match(n)]
    if bad:
        raise Problem(f"{CONFIG} has variable names that are not valid: {', '.join(bad)}")
    return cfg


def check_vault(cfg: dict, token: str) -> None:
    """Least privilege: the service account must open exactly the configured vault."""
    opened = vaults(token)
    if opened != [cfg["vault"]]:
        raise Problem(f"the service account opens [{', '.join(opened)}], not only '{cfg['vault']}'; "
                      "nothing loaded")


def env_values(start: str, names: list[str], timeout: float = 8) -> dict[str, str]:
    """Values of the named variables from the project's config, for a hook (which cannot see
    the session's environment). Empty when the project has no config or no stored token;
    Problem when a read fails. One 1Password read per name, no vault listing: nothing is
    exported, so the least-privilege check stays with `load`."""
    root = project_root(start, min(3, timeout / 3))
    cfg = load_config(root)
    if not cfg:
        return {}
    token = token_for(cfg)
    if not token:
        return {}
    refs = cfg.get("env", {})
    return {n: read_ref(refs[n], token, timeout) for n in names if n in refs}


# --- commands --------------------------------------------------------------------------------

def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def load(start: str) -> str:
    """The SessionStart hook: one line for the session, never a value."""
    root = project_root(start)
    try:
        cfg = load_config(root)
    except Problem as exc:
        return f"{SAY} {exc}. No tokens loaded."
    if not cfg:
        if read_stored(default_credential(root)):
            return (f"{SAY} a token is stored for this project, but {CONFIG} is missing. "
                    f"No tokens loaded; the user runs: python \"{Path(__file__)}\" setup")
        return ""  # a project without agent credentials: silent
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return f"{SAY} CLAUDE_ENV_FILE is not set, so no tokens were loaded."
    token = token_for(cfg)
    if not token:
        return (f"{SAY} no token stored as '{cfg['credential']}'. No tokens loaded; the user runs "
                f"once, in their own terminal: python \"{Path(__file__)}\" setup \"{root}\"")
    try:
        check_vault(cfg, token)
    except Problem as exc:
        return f"{SAY} {exc}."
    lines, loaded, failed = [], [], []
    if cfg.get("export_service_account_token"):
        lines.append(f"export OP_SERVICE_ACCOUNT_TOKEN={_quote(token)}")
        loaded.append("OP_SERVICE_ACCOUNT_TOKEN")
    for name, ref in cfg.get("env", {}).items():
        try:
            lines.append(f"export {name}={_quote(read_ref(str(ref), token))}")
            loaded.append(name)
        except Problem as exc:
            failed.append(f"{name} ({exc})")
    if lines:
        with open(env_file, "a", encoding="utf-8", newline="\n") as f:  # bash sources it: LF
            f.write("\n".join(lines) + "\n")
    msg = f"{SAY} Loaded for this session (names only): {', '.join(loaded) or 'none'}"
    return msg + (f". Could not read: {'; '.join(failed)}" if failed else "")


def _clipboard_token() -> str:
    if os.name != "nt":
        import getpass
        return getpass.getpass("Paste the service account token (hidden), then press Enter: ").strip()
    input("In 1Password, copy this project's service account token, then press Enter here. ")
    ps = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    out = subprocess.run(ps + ["Get-Clipboard -Raw"], capture_output=True, text=True, timeout=15)
    subprocess.run(ps + ["Set-Clipboard -Value ' '"], capture_output=True, timeout=15)  # clear it
    return (out.stdout or "").strip()


def setup(start: str) -> list[str]:
    """Interactive, in the user's own terminal. Returns the lines to show (names only)."""
    root = project_root(start)
    old = load_config(root) or {}
    name = old.get("credential") or default_credential(root)
    token = read_stored(name)
    if token and input(f"A token is stored as '{name}'. Keep it? [Y/n] ").strip().lower() in ("", "y", "yes"):
        pass
    else:
        token = _clipboard_token()
    if not token.startswith("ops_"):
        raise Problem("that is not a service account token (it starts with ops_). Nothing stored")
    opened = vaults(token)
    if len(opened) != 1:
        raise Problem(f"the service account opens [{', '.join(opened)}]; it must open exactly one "
                      "vault, the project's development vault. Nothing stored")
    vault = opened[0]
    if old.get("vault") and old["vault"] != vault:
        raise Problem(f"the service account opens '{vault}', but {CONFIG} names '{old['vault']}'. "
                      "Nothing stored")
    write_stored(name, token)
    if read_stored(name) != token:
        raise Problem("Windows did not keep the token")
    env = dict(old.get("env") or {})
    found = find_tokens(vault, token)
    for var, ref in found.items():
        env.setdefault(var, ref)
    cfg = {"credential": name, "vault": vault,
           "export_service_account_token": old.get("export_service_account_token", True), "env": env}
    path = root / CONFIG
    if cfg != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = [v for v in KNOWN_TOKENS if v not in env]
    lines = [f"Stored as '{name}'. The service account opens: {vault}",
             f"{CONFIG}: " + (", ".join(f"{k} <- {v}" for k, v in env.items()) or "(no variables)")]
    if missing:
        lines.append("Not found (an API Credential item whose title names it, exactly one): "
                     + ", ".join(f"{v} ({KNOWN_TOKENS[v]})" for v in missing))
    lines.append("Start a new Claude Code session in this project to load them.")
    return lines


def check(start: str) -> dict:
    root = project_root(start)
    cfg = load_config(root)
    name = (cfg or {}).get("credential") or default_credential(root)
    token = (cfg and token_for(cfg)) or read_stored(name)
    report = {"project": str(root), "config": bool(cfg), "credential": name, "stored": bool(token),
              "op": bool(op_path()), "env": sorted((cfg or {}).get("env", {})),
              "in_this_session": sorted(n for n in (cfg or {}).get("env", {}) if os.environ.get(n))}
    if token:
        try:
            report["vaults"] = vaults(token)
        except Problem as exc:
            report["problem"] = str(exc)
    return report


def main(argv: list[str]) -> int:
    if not argv:  # the SessionStart hook: never fails, never blocks
        try:
            raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace") if not sys.stdin.isatty() else ""
            try:
                event = json.loads(raw) if raw.strip() else {}
            except ValueError:
                event = {}  # the project folder also comes from CLAUDE_PROJECT_DIR
            event = event if isinstance(event, dict) else {}
            start = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
            msg = load(start)
        except Exception as exc:  # noqa: BLE001  never block a session; never print a value
            msg = f"{SAY} unexpected error ({type(exc).__name__}), no tokens loaded."
        if msg:
            print(msg)
        return 0
    pause = "--pause" in argv
    args = [a for a in argv if a != "--pause"]
    cmd, start = args[0], (args[1] if len(args) > 1 else os.getcwd())
    code = 0
    try:
        if cmd == "setup":
            print("\n".join(setup(start)))
        elif cmd == "check":
            print(json.dumps(check(start), indent=2))
        else:
            print(__doc__)
            code = 2
    except Problem as exc:
        print(f"Stopped: {exc}.")
        code = 1
    if pause:
        input("Press Enter to close. ")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
