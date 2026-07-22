"""The dispatch seam (ADR-22/23): dispatch(role, brief) -> (text, cost/usage).

The backend is a command template per role, never an imported client.
Config shape (the ``dispatch`` key of fleet.json):

    {
      "roles": {
        "foreman-build": {"backend": "command",
                          "argv": ["alloyd", "dispatch", "foreman-build", "--brief", "{brief_path}"]},
        "nightcrew-judge": {"backend": "command",
                            "argv": ["claude", "-p", "--model", "claude-opus-4-8",
                                     "--output-format", "json", "{brief_text}"]},
        "build": {"backend": "openrouter", "model": "anthropic/claude-sonnet-5"}
      }
    }

Placeholders in argv: {brief_path} (brief written to a temp .json file),
{brief_text} (brief JSON inline). OpenRouter key from env OPENROUTER_API_KEY.
"""

import json
import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field


class DispatchError(Exception):
    pass


BANNED_SUBSTRINGS = ("fable", "mythos")


@dataclass
class DispatchResult:
    text: str
    cost_usd: float | None = None  # None on unmetered paths (alloyd/subscription)
    usage: dict = field(default_factory=dict)


def dispatch(role: str, brief: dict, config: dict, cwd=None) -> DispatchResult:
    roles = config.get("roles") or {}
    if role not in roles:
        raise DispatchError(f"no dispatch config for role {role!r}")
    rc = roles[role]
    if _contains_banned_string(rc):
        raise DispatchError(f"dispatch config for role {role!r} contains a banned term")
    backend = rc.get("backend", "command")
    if backend == "command":
        return _run_command(rc, brief, cwd)
    if backend == "openrouter":
        return _run_openrouter(rc, brief)
    raise DispatchError(f"unknown backend {backend!r} for role {role!r}")


def _contains_banned_string(value) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in BANNED_SUBSTRINGS)
    if isinstance(value, dict):
        return any(_contains_banned_string(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_banned_string(v) for v in value)
    return False


def _run_command(rc: dict, brief: dict, cwd=None) -> DispatchResult:
    brief_text = json.dumps(brief)
    brief_path = None
    argv = rc["argv"]
    if any("{brief_path}" in a for a in argv):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, prefix="nightcrew-brief-"
        ) as f:
            f.write(brief_text)
            brief_path = f.name
    argv = [a.replace("{brief_path}", brief_path or "").replace("{brief_text}", brief_text)
            for a in argv]
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=rc.get("timeout", 3600), cwd=cwd)
    finally:
        if brief_path:
            os.unlink(brief_path)
    if r.returncode != 0:
        raise DispatchError(f"{argv[0]} exited {r.returncode}: {r.stderr.strip()[:500]}")
    return _parse_output(r.stdout)


def _parse_output(stdout: str) -> DispatchResult:
    # claude -p --output-format json → {"result":…, "total_cost_usd":…, "usage":…};
    # alloyd streams JSONL (codex events). Fall back to raw stdout as the text.
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        jsonl = _parse_jsonl(stdout)
        return jsonl or DispatchResult(text=stdout.strip())
    if not isinstance(data, dict):
        return DispatchResult(text=stdout.strip())
    text = data.get("result") or data.get("text") or data.get("output") or stdout.strip()
    cost = data.get("total_cost_usd") or data.get("cost_usd") or data.get("cost")
    return DispatchResult(
        text=str(text),
        cost_usd=float(cost) if cost is not None else None,
        usage=data.get("usage") or {},
    )


def _parse_jsonl(stdout: str) -> DispatchResult | None:
    # alloyd smoke 2026-07-21: codex JSONL — agent text in
    # {"type":"item.completed","item":{"type":"agent_message","text":…}},
    # usage in {"type":"turn.completed","usage":{…}}. Unmetered → cost None.
    texts, usage = [], {}
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(ev, dict):
            continue
        item = ev.get("item") or {}
        if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
            texts.append(item.get("text") or "")
        elif ev.get("type") == "turn.completed":
            usage = ev.get("usage") or {}
    if not texts:
        return None
    return DispatchResult(text="\n".join(texts).strip(), usage=usage)


def _run_openrouter(rc: dict, brief: dict) -> DispatchResult:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise DispatchError("OPENROUTER_API_KEY not set")
    req = urllib.request.Request(
        rc.get("url", "https://openrouter.ai/api/v1/chat/completions"),
        data=json.dumps({
            "model": rc["model"],
            "usage": {"include": True},
            "messages": [{"role": "user", "content": json.dumps(brief)}],
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=rc.get("timeout", 600)) as resp:
        data = json.loads(resp.read())
    usage = data.get("usage") or {}
    return DispatchResult(
        text=data["choices"][0]["message"]["content"],
        cost_usd=usage.get("cost"),
        usage=usage,
    )
