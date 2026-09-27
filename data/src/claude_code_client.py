"""Shared client for the locally authenticated Claude Code CLI.

Used by both reconstruct.py (Phase 3: page reconstruction) and
validate_with_claude.py (Phase 3c: visual/semantic validation). Always
goes through the `claude` binary and whatever session `claude auth
login` already set up -- no ANTHROPIC_API_KEY, no direct Anthropic API
calls, ever.
"""

import json
import shutil
import subprocess


def check_claude_cli() -> None:
    """Fail fast if the Claude Code CLI isn't installed/on PATH.

    Authentication itself (subscription login) is entirely Claude Code's
    own concern -- this pipeline never reads, stores, or handles an API
    key, cookie, or session token.
    """
    if shutil.which("claude") is None:
        raise RuntimeError(
            "The 'claude' CLI was not found on PATH. Install Claude Code "
            "and make sure you're logged in (check with `claude auth status`)."
        )


def strip_code_fence(text: str) -> str:
    """Defensive cleanup in case the model wraps its response in a
    ``` fence despite being told not to. Only strips the fence markers,
    never touches the content between them."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if len(lines) > 1 and lines[-1].strip() == "```":
        lines = lines[1:-1]
    else:
        lines = lines[1:]
    return "\n".join(lines).strip()


def call_claude_code(
    system_prompt: str,
    user_content: list,
    model: str,
    timeout_seconds: int,
    json_schema: dict | None = None,
) -> str:
    """Run one stateless request through the locally authenticated Claude
    Code CLI and return its plain-text result.

    Uses --input-format/--output-format stream-json so the request can
    carry text+image content blocks (fed via stdin, not written to
    disk), and reads the final {"type": "result", ...} event for the
    response text. If json_schema is given, passes --json-schema so the
    CLI enforces structured output; the returned string is then clean
    JSON text ready for json.loads(), no fences or preamble.
    """
    message = {"type": "user", "message": {"role": "user", "content": user_content}}
    payload = json.dumps(message) + "\n"

    command = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--system-prompt", system_prompt,
        "--tools", "",
        "--model", model,
        "--no-session-persistence",
    ]
    if json_schema is not None:
        command += ["--json-schema", json.dumps(json_schema)]

    try:
        completed = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("The 'claude' CLI was not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude -p timed out after {timeout_seconds}s") from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"claude -p exited with code {completed.returncode}: "
            f"{completed.stderr.strip() or '(no stderr output)'}"
        )

    result_event = None
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # ignore malformed/partial lines, keep scanning
        if event.get("type") == "result":
            result_event = event

    if result_event is None:
        raise RuntimeError(
            "No 'result' event found in claude -p output "
            f"(stderr: {completed.stderr.strip() or '(empty)'})"
        )

    if result_event.get("is_error"):
        raise RuntimeError(
            f"claude -p reported an error ({result_event.get('subtype', 'unknown_error')}): "
            f"{result_event.get('result')}"
        )

    result_text = result_event.get("result")
    if not isinstance(result_text, str):
        raise RuntimeError(f"claude -p 'result' event had no text result: {result_event}")

    return result_text
