"""
Article-to-Lab Prompt Builder v0.1.

Builds system + user message pairs for LLM-based Guided Practice Lab generation
from article text. Output is structured to match the LabDraft JSON schema.

Design invariants:
  - Prompt never exposes raw secrets, credentials, kubeconfig, or private keys
  - Article text is truncated to safe length before inclusion
  - Credential-like patterns in article text are redacted before inclusion in prompt
  - Prompt instructs LLM to produce a Guided Practice Lab (not Assessment Lab)
  - Prompt instructs LLM to output ONLY a JSON object (no prose, no markdown fences)
  - Output prohibitions are enumerated in the system message
  - prompt builder output NEVER enters API responses
  - hidden prompts NEVER enter logs
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# Max characters of article text to include in the prompt
_MAX_ARTICLE_TEXT_LEN = 4000
_MAX_TITLE_LEN = 200
_MAX_READER_LEN = 200
_MAX_LAB_TITLE_LEN = 200

# Credential-like patterns to redact from article text before sending to LLM
_REDACT_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._=+/\-]{8,}"),
    re.compile(
        r"(?i)(token|password|secret|private_key|credential|kubeconfig|api[_-]?key)\s*[=:]\s*\S+"
    ),
    re.compile(r"eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def _redact_article_text(text: str) -> str:
    cleaned = text
    for pat in _REDACT_PATTERNS:
        cleaned = pat.sub("[REMOVED]", cleaned)
    return cleaned[:_MAX_ARTICLE_TEXT_LEN]


# ---------------------------------------------------------------------------
# Supported domain hints
# ---------------------------------------------------------------------------

_DOMAIN_HINTS = {
    "k8s": (
        "Kubernetes domain (kubectl, pods, deployments, namespaces, configmaps, secrets, "
        "services, endpoints — services/endpoints added for the Service-no-Endpoints lab, "
        "Lab-to-Article Sprint Day 1). "
        "Verifier primitives actually implemented at runtime — use ONLY these, never "
        "any other VerifyType schema enum value (the schema declares more types than "
        "the runtime supports; using an unimplemented one — e.g. pod_ready, which looks "
        "plausible but was never wired up — permanently blocks step progression with "
        "verify_type_not_implemented and was only caught by live rehearsal, not static "
        "validation): namespace_exists, namespace_not_exists, pod_running, "
        "service_exists, service_has_endpoints, deployment_ready, deployment_unavailable, "
        "configmap_exists, secret_exists. "
        "service_has_endpoints checks the Service's core/v1 Endpoints object has at least "
        "one address (equivalent to `kubectl get endpoints <name>`) — use it for any lab "
        "step that must confirm a Service selector now matches Ready Pods. Never rely on "
        "`kubectl describe service`'s Endpoints line as the learner-facing evidence for "
        "this: on this K3s version that field is unreliable and can keep showing <none> "
        "even after the Service is correctly routing traffic (Selector/Type fields are "
        "unaffected) — always use `kubectl get endpoints` in commands/observe text instead. "
        "Services: learner RBAC grants create/get/list/watch/delete only — no update/patch "
        "(K8s RBAC can't restrict by spec.type, so patch was withheld entirely to prevent "
        "escalating a ClusterIP Service to NodePort/LoadBalancer; see kubectl_executor.py "
        "and learner_credentials.py). Never generate a step that patches a Service — fix "
        "a wrong selector via `kubectl delete service` + `kubectl expose deployment ... "
        "--name=<svc>` instead, which derives the selector from the Deployment's real Pod "
        "labels and needs no patch permission at all. Also note: `kubectl create service "
        "clusterip <name> --tcp=...` without --selector defaults selector to "
        "`app=<service-name>`, not to any existing Deployment's labels — useful for "
        "authentically constructing a Service-selector-mismatch scenario without needing "
        "any patch step. "
        "Cleanup: namespace deletion only. No cluster-scoped resource creation."
    ),
    "linux": (
        "Linux domain (file permissions, file operations within ~/workspace only). "
        "Verifier primitives: file_exists, file_mode, file_content_contains, "
        "dir_exists, symlink_target. "
        "Cleanup: workspace directory deletion (no sudo, no /etc, no systemctl)."
    ),
}

# ---------------------------------------------------------------------------
# System and contract text
# ---------------------------------------------------------------------------

_SYSTEM_PROHIBITIONS = """\
HARD CONSTRAINTS (violating any causes your output to be DISCARDED):
1. Output ONLY a JSON object. No markdown fences. No prose. No explanations.
2. No chain-of-thought, no reasoning, no commentary outside the JSON.
3. No secrets: tokens, passwords, credentials, kubeconfig, API keys, private keys.
4. Set "publish_status" to "draft" only (or omit it). NEVER set it to "published".
5. Do NOT request, suggest, or imply any publish or lab-start actions.
6. Do NOT include: raw_model_output, hidden_prompt, chain_of_thought, provider_trace_id.
7. No Traceback, stack trace, or raw exception text anywhere in the output.
8. Commands must be executable in an isolated sandbox — no sudo, no real credentials,
   no production system access, no internet-required commands (unless domain allows).
9. Each step verifier must use ONLY the domain's approved primitives listed above.
10. cleanup field MUST be present and declare how the environment is cleaned up.
"""

_K8S_COMMAND_CONSTRAINTS = """\
COMMAND GENERATION RULES (K8s domain — kubectl_executor.py enforces these at runtime
and StaticValidator rejects violations before publish; a lab that violates these will
either fail for the learner or be discarded before it ever reaches them):

1. Each string in "commands" is executed as a single, standalone "kubectl ..."
   invocation. It is NOT run through a shell: no variable assignment (X=$(...)),
   no command substitution, no pipes (|), no && / ; chaining, no $VAR expansion.
   Every command string must start with the literal word "kubectl".
2. To target a Pod without knowing its exact name in advance, use a label selector
   directly in the command — do NOT capture a name into a variable first:
   GOOD: kubectl logs -l app=my-app --previous
   GOOD: kubectl describe pods -l app=my-app
   BAD:  POD_NAME=$(kubectl get pods -o jsonpath='{.items[0].metadata.name}')
3. Never generate "kubectl delete namespace" or any get/describe/delete/edit on a
   cluster-scoped resource (namespace, node, clusterrole, clusterrolebinding,
   persistentvolume, storageclass). Namespace cleanup happens automatically when the
   lab session ends — never write a step or verify command that deletes or inspects
   the namespace itself.
4. Never use -o yaml, -o json, -o jsonpath, or any --output format other than the
   default table, "wide", or "name" — these are blocked because they can expose
   secret values.
5. Never write -n or --namespace in a command — the platform always injects the
   learner's own namespace automatically; any namespace flag you write is ignored.
6. Never use: kubectl exec, port-forward, proxy, attach, cp, debug, run, plugin,
   config, "create token", auth, or --all-namespaces / -A.
7. Never use --kubeconfig — the platform always injects its own.
"""

_LINUX_COMMAND_CONSTRAINTS = """\
COMMAND GENERATION RULES (Linux domain — linux_command_executor.py enforces these
at runtime; a lab that violates these will fail for the learner):

1. Each command is executed as argv directly (no shell). Do NOT use shell
   metacharacters in any argument: ; & | ` $ ( ) { } < > \\ !  — no pipes,
   no substitution, no redirection, no chaining.
2. The first word of each command must be one of: pwd, ls, mkdir, touch, echo,
   cat, chmod, stat, find, rm, cp, mv, wc, head, tail, grep, diff, test, [.
   Never use: sudo, su, systemctl, ssh/scp/rsync, curl/wget, package managers
   (apt/yum/apk/pip), or any interpreter (python, bash, sh, perl, node).
3. All paths must be relative to the workspace and stay within it — never use an
   absolute path (starting with /) and never use ".." to escape the workspace.
"""

_JSON_SCHEMA_SUMMARY = """\
REQUIRED JSON SCHEMA (all fields required unless marked optional):
{
  "schema_version": "1.0",
  "source_article_id": "llm-generated",
  "title": "<lab title string>",
  "description": "<experiment_background: 2-4 sentences why this topic matters>",
  "experiment_background": "<same as description or expand>",
  "prerequisites": ["<prerequisite 1>", "<prerequisite 2>"],
  "estimated_duration_minutes": <integer 15-60>,
  "completion_summary": "<what learner achieved in 2-3 sentences>",
  "runtime_requirements": {
    "namespace_strategy": "dedicated"
  },
  "steps": [
    {
      "step_id": "<step-N>",
      "order": <integer>,
      "why": "<why this step matters — learning rationale>",
      "do": "<what the learner does — clear instruction>",
      "commands": ["<command 1>", "<command 2>"],
      "observe": "<expected output or observable result>",
      "troubleshoot": "<what to do if it doesn't work>",
      "explain": {
        "concept": "<core concept this step teaches>",
        "observation": "<what the learner should observe>"
      },
      "verify": [
        {
          "verify_id": "<step-N_v1>",
          "type": "<verifier primitive name>",
          "namespace": "{{lab_namespace}}",
          "name": "<resource name>"
        }
      ]
    }
  ],
  "cleanup": {
    "namespace_cleanup": {
      "type": "delete_namespace",
      "namespace": "{{lab_namespace}}"
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_article_to_lab_messages(
    article_text: str,
    *,
    article_title: str,
    target_domain: str,
    intended_reader: Optional[str] = None,
    desired_lab_title: Optional[str] = None,
    operability_status: str = "directly_lab_ready",
) -> tuple[str, str]:
    """
    Return (system_message, user_message) for an article-to-lab generation request.

    The caller MUST NOT log either message or include them in API responses.
    article_text is redacted and truncated before inclusion.

    Args:
        article_text: Raw article text (will be redacted + truncated — not stored).
        article_title: Title of the article (truncated to safe length).
        target_domain: "k8s" or "linux".
        intended_reader: Audience description (optional).
        desired_lab_title: Admin-suggested lab title (optional).
        operability_status: "directly_lab_ready" or "partially_lab_ready".
    """
    domain_key = target_domain.lower() if target_domain else "k8s"
    domain_hint = _DOMAIN_HINTS.get(domain_key, _DOMAIN_HINTS["k8s"])
    command_constraints = (
        _LINUX_COMMAND_CONSTRAINTS if domain_key == "linux" else _K8S_COMMAND_CONSTRAINTS
    )

    safe_title = (article_title or "Untitled")[:_MAX_TITLE_LEN]
    safe_reader = (intended_reader or "intermediate practitioner")[:_MAX_READER_LEN]
    safe_lab_title = (desired_lab_title or "")[:_MAX_LAB_TITLE_LEN]
    safe_text = _redact_article_text(article_text)

    partial_note = ""
    if operability_status == "partially_lab_ready":
        partial_note = (
            "\nNOTE: This article is PARTIALLY_LAB_READY. "
            "Generate the best lab possible from the available content. "
            "Mark any steps that require clarification with [NEEDS_REVIEW] in the 'troubleshoot' field. "
            "Do NOT fabricate commands that are not implied by the article.\n"
        )

    system = (
        "You are a Guided Practice Lab generator for a cloud-native education platform. "
        "You produce structured lab drafts in JSON format that allow learners to practice "
        "hands-on skills in an isolated sandbox environment. "
        "You ONLY produce Guided Practice Labs — NOT assessment labs, NOT quizzes, NOT conceptual exams.\n\n"
        f"Domain context:\n{domain_hint}\n\n"
        + _JSON_SCHEMA_SUMMARY
        + "\n"
        + command_constraints
        + "\n"
        + _SYSTEM_PROHIBITIONS
    )

    user_parts = [
        f"Generate a Guided Practice Lab from the following article.\n\n"
        f"Article title: {safe_title}\n"
        f"Target domain: {domain_key}\n"
        f"Intended reader: {safe_reader}\n"
    ]
    if safe_lab_title:
        user_parts.append(f"Desired lab title: {safe_lab_title}\n")
    if partial_note:
        user_parts.append(partial_note)
    user_parts.append(f"\nArticle text:\n---\n{safe_text}\n---\n")
    user_parts.append(
        "\nGenerate a complete Guided Practice Lab JSON. "
        "Include 3-6 steps, each with why/do/commands/observe/troubleshoot/explain/verify. "
        "Commands must be sandbox-safe and executable without real credentials. "
        "The lab must have a cleanup section."
    )

    user = "\n".join(user_parts)
    return system, user


def article_text_contains_prohibited_content(text: str) -> bool:
    """True if the article text contains credential-like patterns that should block generation."""
    for pat in _REDACT_PATTERNS[:4]:
        if pat.search(text):
            return True
    return False
