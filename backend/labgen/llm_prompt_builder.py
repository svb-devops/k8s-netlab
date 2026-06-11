"""
LLM Prompt Builder v0.1.

Constructs JSON-only system + user message pairs for the OpenAI-compatible provider.

Design invariants:
  - prompt builder output NEVER enters API responses
  - hidden prompts NEVER enter logs
  - full raw contract text NEVER sent to provider; only a safe summary
  - user_prompt is sanitized and length-limited before use
  - tests assert structural constraints and red-lines only — never snapshot full prompt text
"""

from __future__ import annotations

import re
from typing import Optional


_MAX_USER_PROMPT_LEN = 1800
_MAX_CONSTRAINTS_SUMMARY_LEN = 400

_PROHIBITED_PROMPT_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)kubeconfig"),
    re.compile(r"(?i)(bearer|authorization)\s*[=:\-]?\s*\S"),
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"(?i)(api_key|private_key|secret|password|credential)\s*[=:]\s*\S"),
]

_CONTRACT_SUMMARY = """\
CONTRACT SUMMARY (v0.1 — abbreviated for context):
- Output a single JSON object only. No markdown. No explanatory text. No chain-of-thought.
- Required top-level fields: schema_version, source_article_id, title, description,
  estimated_duration_minutes, runtime_requirements, steps, cleanup.
- Each step must include: step_id, order, why, do, observe, explain (concept + observation).
  Steps may optionally include verify_template with type and expected_value.
- cleanup must declare namespace_cleanup with a mode field.
- runtime_requirements must include namespace_strategy (one of: dedicated, shared).
- Do NOT include: secrets, tokens, kubeconfig, credentials, publish_status=published,
  raw_model_output, chain_of_thought, hidden_prompt.
- Do NOT request publish or lab start actions in your output.
"""

_SYSTEM_PROHIBITIONS = """\
PROHIBITIONS (hard constraints — violating any causes your output to be discarded):
1. Output ONLY a JSON object. No markdown, no code fences, no prose.
2. No chain-of-thought, no reasoning text, no explanatory commentary.
3. No secrets: kubeconfig, tokens, passwords, credentials, API keys, private keys.
4. Do NOT set publish_status to "published" — omit this field entirely or set to "draft".
5. Do NOT request, suggest, or imply any publish or lab-start actions.
6. Do NOT include raw_model_output, hidden_prompt, chain_of_thought, provider_trace_id.
7. No Traceback, stack trace, or raw exception text.
"""


def _sanitize_user_input(text: str, max_len: int) -> str:
    """Remove credential-like patterns and truncate."""
    cleaned = text
    for pat in _PROHIBITED_PROMPT_PATTERNS:
        cleaned = pat.sub("[REMOVED]", cleaned)
    return cleaned[:max_len]


def _build_template_hint(
    selected_template_id: Optional[str],
    constraints_summary: str,
) -> str:
    parts: list[str] = []
    if selected_template_id:
        parts.append(f"Suggested template: {selected_template_id}")
    if constraints_summary:
        safe_constraints = _sanitize_user_input(
            constraints_summary, _MAX_CONSTRAINTS_SUMMARY_LEN
        )
        parts.append(f"Constraints: {safe_constraints}")
    return "\n".join(parts) if parts else ""


def build_generation_messages(
    sanitized_user_prompt: str,
    selected_template_id: Optional[str] = None,
    constraints_summary: str = "",
    purpose: str = "draft_generation",
) -> tuple[str, str]:
    """
    Return (system_message, user_message) for a draft generation request.

    The caller must NOT log either message or include them in API responses.
    Both strings are safe to pass to an OpenAI-compatible chat endpoint.
    """
    safe_prompt = _sanitize_user_input(sanitized_user_prompt, _MAX_USER_PROMPT_LEN)
    template_hint = _build_template_hint(selected_template_id, constraints_summary)

    system = (
        "You are a technical lab generator for a Kubernetes networking education platform. "
        "You produce structured lab drafts in JSON format only.\n\n"
        + _CONTRACT_SUMMARY
        + "\n"
        + _SYSTEM_PROHIBITIONS
    )

    user_parts = [f"Generate a lab draft for the following topic:\n\n{safe_prompt}"]
    if template_hint:
        user_parts.append(f"\n{template_hint}")
    if purpose == "draft_repair":
        user_parts.append("\nThis is a REPAIR request. Fix the identified issues only.")

    user = "\n".join(user_parts)
    return system, user


def build_repair_messages(
    sanitized_user_prompt: str,
    validation_issues_summary: str,
    selected_template_id: Optional[str] = None,
) -> tuple[str, str]:
    """
    Return (system_message, user_message) for a draft repair request.

    Repair prompt does NOT include the raw original candidate — only the issues summary.
    """
    safe_prompt = _sanitize_user_input(sanitized_user_prompt, _MAX_USER_PROMPT_LEN)
    safe_issues = _sanitize_user_input(validation_issues_summary, 600)

    system = (
        "You are a technical lab generator for a Kubernetes networking education platform. "
        "You fix broken lab drafts by producing a corrected JSON object.\n\n"
        + _CONTRACT_SUMMARY
        + "\n"
        + _SYSTEM_PROHIBITIONS
    )

    template_hint = _build_template_hint(selected_template_id, "")
    user_parts = [
        f"The original topic was:\n{safe_prompt}\n",
        f"Validation issues to fix:\n{safe_issues}\n",
        "Produce a corrected JSON lab draft that resolves all listed issues.",
    ]
    if template_hint:
        user_parts.append(f"\n{template_hint}")

    user = "\n".join(user_parts)
    return system, user


def prompt_contains_prohibited_content(text: str) -> bool:
    """True if the text contains credential-like or prohibited patterns."""
    for pat in _PROHIBITED_PROMPT_PATTERNS:
        if pat.search(text):
            return True
    return False
