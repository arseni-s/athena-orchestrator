"""Copies one environment's variables from 1Password to Railway (athena-orchestrator template).

1Password is where every value lives; Railway holds a copy. Each environment has one 1Password
item, `railway-<environment>`, with one field per variable: the field's label is the variable's
name (`TELEGRAM_BOT_TOKEN`), its value the value. Fields whose label is not an UPPER_CASE name
are ignored, so the item can carry notes.

    python scripts/push_secrets.py development           push development (the agent may run it)
    python scripts/push_secrets.py development --check   compare names only, change nothing
    python scripts/push_secrets.py production            push production (only you, by hand)

What it does, per Railway service:
- reads the item once (`op item get --format json --reveal`), and Railway's variables once;
- sets each variable that is missing or different, passing the value on standard input
  (`railway variable set NAME --stdin`), never on a command line;
- development: only the last change redeploys, so a push is one deploy;
- production: every change uses `--skip-deploys`. Production deploys when you deploy it
  from the Railway dashboard, and that deploy picks the new values up;
- never deletes: a variable on Railway that is not in 1Password is listed, and you decide.
  Railway's own `RAILWAY_*` variables are left out of that list.

It never prints a value: only names and counts. A failing command's output is printed with
every value blanked out.

Production is refused unless you run it yourself: it needs a terminal to type "production"
into, and refuses when `OP_SERVICE_ACCOUNT_TOKEN` is set (the agent's service account has no
production vault anyway, and its Railway token reaches development only).

Needs Python 3.11+, the 1Password CLI (`op`) and the Railway CLI, standard library only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

TARGETS = {
    "development": {"vault": "{{op_vault_dev}}", "environment": "{{railway_env_dev}}"},
    "production": {"vault": "{{op_vault_prod}}", "environment": "{{railway_env_prod}}"},
}
# The Railway services that get these variables; one entry per service.
SERVICES = ["{{railway_service}}"]
NAME = re.compile(r"[A-Z][A-Z0-9_]*")
TIMEOUT_S = 60


class Failed(Exception):
    pass


def run(cmd: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Runs a command with its output captured, never shown. Tests replace this."""
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=TIMEOUT_S)


def blank(text: str, values: list[str]) -> str:
    for v in sorted((v for v in values if v), key=len, reverse=True):
        text = text.replace(v, "***")
    return text


def call(cmd: list[str], values: list[str], stdin: str | None = None) -> str:
    try:
        done = run(cmd, stdin)
    except (OSError, subprocess.SubprocessError) as e:
        raise Failed(f"`{cmd[0]} {cmd[1]}` could not run: {type(e).__name__}")
    if done.returncode != 0:
        said = blank((done.stderr or done.stdout or "").strip(), values)[-500:]
        raise Failed(f"`{' '.join(cmd[:3])}` failed (exit {done.returncode}): {said}")
    return done.stdout


def from_1password(environment: str, vault: str) -> dict[str, str]:
    item = f"railway-{environment}"
    out = call(["op", "item", "get", item, "--vault", vault, "--format", "json", "--reveal"], [])
    try:
        fields = json.loads(out).get("fields") or []
    except (ValueError, AttributeError):
        raise Failed(f"1Password item {item} in vault {vault}: unreadable output")
    found = {f.get("label", ""): f.get("value") for f in fields if isinstance(f, dict)}
    values = {k: v for k, v in found.items() if NAME.fullmatch(k or "") and isinstance(v, str) and v != ""}
    if not values:
        raise Failed(f"1Password item {item} in vault {vault} has no UPPER_CASE fields with values")
    return values


def from_railway(service: str, environment: str, secret: list[str]) -> dict[str, str]:
    out = call(["railway", "variable", "list", "--service", service, "--environment", environment, "--json"], secret)
    try:
        data = json.loads(out)
    except ValueError:
        raise Failed(f"Railway variables of {service} ({environment}): unreadable output")
    if isinstance(data, list):  # `[{"name": ..., "value": ...}]`
        data = {d.get("name"): d.get("value") for d in data if isinstance(d, dict)}
    if not isinstance(data, dict):
        raise Failed(f"Railway variables of {service} ({environment}): unexpected output")
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


def confirm_production() -> None:
    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
        raise Failed("production is pushed with your own 1Password login, not a service account: "
                     "OP_SERVICE_ACCOUNT_TOKEN is set")
    if not sys.stdin.isatty():
        raise Failed("production needs you at a terminal: run it in your own shell")
    if input('Push to production? Type "production" to continue: ').strip() != "production":
        raise Failed("not confirmed")


def push(environment: str, check: bool) -> int:
    target = TARGETS[environment]
    if environment == "production" and not check:
        confirm_production()
    wanted = from_1password(environment, target["vault"])
    secret = list(wanted.values())
    for service in SERVICES:
        have = from_railway(service, target["environment"], secret)
        secret += list(have.values())
        changes = sorted(k for k, v in wanted.items() if have.get(k) != v)
        extra = sorted(k for k in have if k not in wanted and not k.startswith("RAILWAY_"))
        print(f"{service} ({environment}): {len(wanted)} in 1Password, {len(have)} on Railway, "
              f"{len(changes)} to set")
        if changes:
            print(f"  {'to set' if check else 'setting'}: {', '.join(changes)}")
        if extra:
            print(f"  only on Railway (not in 1Password, left as they are): {', '.join(extra)}")
        if check:
            continue
        for n, name in enumerate(changes):
            cmd = ["railway", "variable", "set", name, "--stdin", "--service", service,
                   "--environment", target["environment"]]
            if environment == "production" or n < len(changes) - 1:
                cmd.append("--skip-deploys")
            call(cmd, secret, stdin=wanted[name])
        if changes and environment == "production":
            print("  production is not redeployed: deploy it from the Railway dashboard when ready")
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--check"]
    if len(args) != 1 or args[0] not in TARGETS:
        print(f"usage: push_secrets.py {{{'|'.join(TARGETS)}}} [--check]", file=sys.stderr)
        return 2
    try:
        return push(args[0], "--check" in argv)
    except Failed as e:
        print(f"push_secrets: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
