"""
Generation Template Pack v0.1.

Deterministic, LLM-free templates producing Contract v0.1 LabDraft candidates.
Each template enforces a pedagogical loop:
  learner goal → setup/context → challenge steps → verifier expectation → completion condition.

No LLM, no network, no provider SDK, no API keys.
"""
from __future__ import annotations

import abc
import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from backend.labgen.models import (
    CleanupNamespace,
    CleanupSpec,
    ExplainField,
    LabDraft,
    RuntimeRequirements,
    Step,
    VerifyTemplate,
    VerifyType,
)


# ---------------------------------------------------------------------------
# Template IDs
# ---------------------------------------------------------------------------


class GenerationTemplateId(str, Enum):
    PYTHON_BASICS = "PYTHON_BASICS"
    HTTP_API_BASICS = "HTTP_API_BASICS"
    DATA_TRANSFORM_BASICS = "DATA_TRANSFORM_BASICS"


# Selection fallback precedence (highest priority first)
_SELECTION_PRECEDENCE: list[GenerationTemplateId] = [
    GenerationTemplateId.PYTHON_BASICS,
    GenerationTemplateId.HTTP_API_BASICS,
    GenerationTemplateId.DATA_TRANSFORM_BASICS,
]


# ---------------------------------------------------------------------------
# Selection result
# ---------------------------------------------------------------------------


class GenerationTemplateSelectionResult(BaseModel):
    selected_template_id: GenerationTemplateId
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Keyword sets for selection  (word-boundary matched, lowercase)
# ---------------------------------------------------------------------------

_KEYWORDS: dict[GenerationTemplateId, frozenset[str]] = {
    GenerationTemplateId.PYTHON_BASICS: frozenset({
        "python", "loop", "function", "list", "variable", "condition",
        "dictionary", "dict", "file", "string", "script", "range",
        "iteration", "class", "import", "print",
    }),
    GenerationTemplateId.HTTP_API_BASICS: frozenset({
        "api", "http", "json", "status", "request", "response",
        "endpoint", "rest", "curl", "fetch", "header", "url",
        "client", "server",
    }),
    GenerationTemplateId.DATA_TRANSFORM_BASICS: frozenset({
        "csv", "transform", "aggregate", "clean", "format",
        "convert", "parse", "data", "dataframe", "pipeline",
        "column", "row", "filter",
    }),
}

# Pre-compiled patterns for fast matching at module load time
_COMPILED_PATTERNS: dict[GenerationTemplateId, list[re.Pattern]] = {
    tid: [re.compile(r"\b" + re.escape(kw) + r"\b") for kw in kws]
    for tid, kws in _KEYWORDS.items()
}


def _score(normalized: str, patterns: list[re.Pattern]) -> int:
    return sum(1 for p in patterns if p.search(normalized))


# ---------------------------------------------------------------------------
# Base template
# ---------------------------------------------------------------------------


class GenerationTemplate(abc.ABC):
    """Produces a deterministic Contract v0.1 LabDraft candidate dict."""

    template_id: GenerationTemplateId
    display_name: str
    description: str

    @abc.abstractmethod
    def build_candidate(
        self,
        user_prompt: str,
        target_audience: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> dict:
        """Return a LabDraft-shaped dict ready for Pydantic parsing."""


# ---------------------------------------------------------------------------
# PYTHON_BASICS
# ---------------------------------------------------------------------------


class _PythonBasicsTemplate(GenerationTemplate):
    template_id = GenerationTemplateId.PYTHON_BASICS
    display_name = "Python Variables and Control Flow"
    description = "Learn Python fundamentals by deploying scripts as Kubernetes Jobs."

    def build_candidate(
        self,
        user_prompt: str,
        target_audience: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> dict:
        steps = [
            Step(
                step_id="pb-step-1",
                order=1,
                why=(
                    "Variables hold data — strings, integers, and lists are the "
                    "most common Python types. Naming variables explicitly builds "
                    "the habit of describing what a program handles."
                ),
                do=(
                    "Apply the python-vars ConfigMap manifest. It stores a script "
                    "that declares one str, one int, and one list, then prints "
                    "each variable's type via the built-in type() call."
                ),
                commands=[
                    "kubectl apply -f manifests/python-vars-configmap.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe="The ConfigMap python-vars exists in the namespace.",
                explain=ExplainField(
                    concept=(
                        "Python variables are labels bound to values. "
                        "type(x) returns the class of x — str, int, or list."
                    ),
                    observation=(
                        "kubectl get configmap python-vars confirms the script "
                        "is stored and ready to mount into a Pod."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="pb-s1-v1",
                        type=VerifyType.CONFIGMAP_EXISTS,
                        name="python-vars",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
            Step(
                step_id="pb-step-2",
                order=2,
                why=(
                    "Loops let a program process every element in a collection. "
                    "A Kubernetes Job runs a script to completion — the same "
                    "model as a production batch process."
                ),
                do=(
                    "Apply the python-loop-job Job manifest. The script iterates "
                    "over a list of numbers using a for loop and prints each value."
                ),
                commands=[
                    "kubectl apply -f manifests/python-loop-job.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe="The Job python-loop-job completes with status Succeeded.",
                explain=ExplainField(
                    concept=(
                        "A for loop binds its loop variable to each element of "
                        "an iterable in turn. range(n) yields integers 0 through n-1."
                    ),
                    observation=(
                        "kubectl get job python-loop-job shows COMPLETIONS 1/1, "
                        "confirming the script ran and exited with code 0."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="pb-s2-v1",
                        type=VerifyType.JOB_COMPLETED,
                        name="python-loop-job",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
            Step(
                step_id="pb-step-3",
                order=3,
                why=(
                    "Functions encapsulate reusable logic. Calling the same function "
                    "with different arguments removes duplication and makes "
                    "programs easier to test."
                ),
                do=(
                    "Apply the python-func-job Job manifest. The script defines a "
                    "greet(name) function and calls it three times with different names."
                ),
                commands=[
                    "kubectl apply -f manifests/python-func-job.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe="The Job python-func-job completes with status Succeeded.",
                explain=ExplainField(
                    concept=(
                        "def defines a function; calling it with () executes its body. "
                        "Parameters receive argument values at call time."
                    ),
                    observation=(
                        "kubectl get job python-func-job shows COMPLETIONS 1/1 "
                        "after the Pod exits successfully."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="pb-s3-v1",
                        type=VerifyType.JOB_COMPLETED,
                        name="python-func-job",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
        ]
        draft = LabDraft(
            source_article_id=f"template:{GenerationTemplateId.PYTHON_BASICS.value}",
            title=self.display_name,
            description=self.description,
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=steps,
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        return draft.model_dump(mode="json")


# ---------------------------------------------------------------------------
# HTTP_API_BASICS
# ---------------------------------------------------------------------------


class _HttpApiBasicsTemplate(GenerationTemplate):
    template_id = GenerationTemplateId.HTTP_API_BASICS
    display_name = "HTTP API Fundamentals: Requests and Responses"
    description = "HTTP API communication using mock endpoints inside Kubernetes."

    def build_candidate(
        self,
        user_prompt: str,
        target_audience: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> dict:
        steps = [
            Step(
                step_id="hab-step-1",
                order=1,
                why=(
                    "HTTP communication requires a live server to respond to requests. "
                    "Deploying a mock API server in the namespace provides a safe, "
                    "isolated target for all subsequent experiments."
                ),
                do=(
                    "Apply the mock-api Deployment and Service manifests. "
                    "The Deployment runs a lightweight nginx container configured "
                    "to return JSON responses; the Service gives it a stable hostname."
                ),
                commands=[
                    "kubectl apply -f manifests/mock-api-deployment.yaml"
                    " -n {{lab_namespace}}",
                    "kubectl apply -f manifests/mock-api-service.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe=(
                    "The mock-api Pod is Ready and the Service mock-api "
                    "exists in the namespace."
                ),
                explain=ExplainField(
                    concept=(
                        "A Deployment manages Pod replicas; a Service provides "
                        "a stable DNS name inside the cluster. Together they "
                        "expose the container as an addressable endpoint."
                    ),
                    observation=(
                        "kubectl get pod and kubectl get svc both show mock-api "
                        "in a ready state before the next step."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="hab-s1-v1",
                        type=VerifyType.POD_READY,
                        name="mock-api",
                        namespace="{{lab_namespace}}",
                    ),
                    VerifyTemplate(
                        verify_id="hab-s1-v2",
                        type=VerifyType.SERVICE_EXISTS,
                        name="mock-api",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
            Step(
                step_id="hab-step-2",
                order=2,
                why=(
                    "GET is the most common HTTP method — it retrieves data without "
                    "modifying server state. Status 200 signals success; other codes "
                    "indicate redirection, client errors, or server errors."
                ),
                do=(
                    "Apply the api-get-job Job manifest. The script uses curl to send "
                    "GET requests to the mock-api Service and logs the HTTP status "
                    "code from each response."
                ),
                commands=[
                    "kubectl apply -f manifests/api-get-job.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe="The Job api-get-job completes with status Succeeded.",
                explain=ExplainField(
                    concept=(
                        "curl -o /dev/null -w '%{http_code}' prints only the "
                        "numeric status code. 200 means OK; 404 means not found."
                    ),
                    observation=(
                        "kubectl logs job/api-get-job shows the 200 status code "
                        "returned by the mock-api Service."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="hab-s2-v1",
                        type=VerifyType.JOB_COMPLETED,
                        name="api-get-job",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
            Step(
                step_id="hab-step-3",
                order=3,
                why=(
                    "POST sends data to a server — typically as a JSON body. "
                    "Reading response headers shows how the server describes "
                    "the format of its reply."
                ),
                do=(
                    "Apply the api-post-job Job manifest. The script sends a POST "
                    "request with a JSON body and reads the Content-Type "
                    "response header."
                ),
                commands=[
                    "kubectl apply -f manifests/api-post-job.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe="The Job api-post-job completes with status Succeeded.",
                explain=ExplainField(
                    concept=(
                        "-H 'Content-Type: application/json' sets a request header; "
                        "-d '{...}' provides the body. The server echo confirms "
                        "the payload was received intact."
                    ),
                    observation=(
                        "kubectl logs job/api-post-job contains the JSON body "
                        "echoed back by the mock-api endpoint."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="hab-s3-v1",
                        type=VerifyType.JOB_COMPLETED,
                        name="api-post-job",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
        ]
        draft = LabDraft(
            source_article_id=f"template:{GenerationTemplateId.HTTP_API_BASICS.value}",
            title=self.display_name,
            description=self.description,
            estimated_duration_minutes=30,
            runtime_requirements=RuntimeRequirements(),
            steps=steps,
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        return draft.model_dump(mode="json")


# ---------------------------------------------------------------------------
# DATA_TRANSFORM_BASICS
# ---------------------------------------------------------------------------


class _DataTransformBasicsTemplate(GenerationTemplate):
    template_id = GenerationTemplateId.DATA_TRANSFORM_BASICS
    display_name = "Data Transformation: Parse, Clean, Aggregate"
    description = "Data pipeline fundamentals: CSV parsing, cleaning, and aggregation."

    def build_candidate(
        self,
        user_prompt: str,
        target_audience: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> dict:
        steps = [
            Step(
                step_id="dtb-step-1",
                order=1,
                why=(
                    "Every pipeline starts with raw input. A ConfigMap simulates "
                    "a file-system source — the same pattern used to inject "
                    "configuration into Pods in production."
                ),
                do=(
                    "Apply the data-source ConfigMap manifest. It contains sample "
                    "CSV data with three columns: name, age, and city."
                ),
                commands=[
                    "kubectl apply -f manifests/data-source-configmap.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe="The ConfigMap data-source exists in the namespace.",
                explain=ExplainField(
                    concept=(
                        "A ConfigMap stores key-value pairs as plain text. "
                        "Mounting it as a volume makes the data available to any "
                        "Pod that reads from that path."
                    ),
                    observation=(
                        "kubectl get configmap data-source confirms the CSV content "
                        "is ready to be consumed by the next Job."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="dtb-s1-v1",
                        type=VerifyType.CONFIGMAP_EXISTS,
                        name="data-source",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
            Step(
                step_id="dtb-step-2",
                order=2,
                why=(
                    "Raw data rarely arrives clean. Stripping whitespace, "
                    "normalising case, and dropping empty rows are the first "
                    "steps in every real pipeline."
                ),
                do=(
                    "Apply the data-clean-job Job manifest. The script reads the "
                    "data-source ConfigMap, parses the CSV, strips whitespace from "
                    "each cell, and writes cleaned output to a new ConfigMap."
                ),
                commands=[
                    "kubectl apply -f manifests/data-clean-job.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe=(
                    "The Job data-clean-job completes and the ConfigMap "
                    "data-cleaned exists in the namespace."
                ),
                explain=ExplainField(
                    concept=(
                        "csv.reader parses each line into a list of strings. "
                        "str.strip() removes leading and trailing whitespace "
                        "from each field."
                    ),
                    observation=(
                        "kubectl get configmap data-cleaned confirms the cleaned "
                        "rows are stored for the aggregation step."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="dtb-s2-v1",
                        type=VerifyType.JOB_COMPLETED,
                        name="data-clean-job",
                        namespace="{{lab_namespace}}",
                    ),
                    VerifyTemplate(
                        verify_id="dtb-s2-v2",
                        type=VerifyType.CONFIGMAP_EXISTS,
                        name="data-cleaned",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
            Step(
                step_id="dtb-step-3",
                order=3,
                why=(
                    "Aggregation — counting, summing, or grouping — turns rows "
                    "into insights. Exporting to JSON makes results portable "
                    "and machine-readable."
                ),
                do=(
                    "Apply the data-aggregate-job Job manifest. The script reads "
                    "the cleaned ConfigMap, counts entries per city, and writes "
                    "a JSON summary to a third ConfigMap."
                ),
                commands=[
                    "kubectl apply -f manifests/data-aggregate-job.yaml"
                    " -n {{lab_namespace}}",
                ],
                observe=(
                    "The Job data-aggregate-job completes and the ConfigMap "
                    "data-summary exists in the namespace."
                ),
                explain=ExplainField(
                    concept=(
                        "A Counter or dict tracks counts per key. "
                        "json.dumps() serialises a Python dict to a JSON string "
                        "that other tools can parse."
                    ),
                    observation=(
                        "kubectl get configmap data-summary confirms the "
                        "city-count JSON is stored and ready to inspect."
                    ),
                ),
                verify=[
                    VerifyTemplate(
                        verify_id="dtb-s3-v1",
                        type=VerifyType.JOB_COMPLETED,
                        name="data-aggregate-job",
                        namespace="{{lab_namespace}}",
                    ),
                    VerifyTemplate(
                        verify_id="dtb-s3-v2",
                        type=VerifyType.CONFIGMAP_EXISTS,
                        name="data-summary",
                        namespace="{{lab_namespace}}",
                    ),
                ],
            ),
        ]
        draft = LabDraft(
            source_article_id=(
                f"template:{GenerationTemplateId.DATA_TRANSFORM_BASICS.value}"
            ),
            title=self.display_name,
            description=self.description,
            estimated_duration_minutes=35,
            runtime_requirements=RuntimeRequirements(),
            steps=steps,
            cleanup=CleanupSpec(namespace_cleanup=CleanupNamespace()),
        )
        return draft.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class GenerationTemplateRegistry:
    """
    Deterministic template registry.

    select() maps user_prompt keywords to a template via word-boundary matching.
    No LLM, no network, no API keys — pure keyword scoring.
    Injection-resistant: user_prompt content is only used for selection scoring,
    never as a command or template override.
    """

    def __init__(self) -> None:
        self._templates: dict[GenerationTemplateId, GenerationTemplate] = {
            GenerationTemplateId.PYTHON_BASICS: _PythonBasicsTemplate(),
            GenerationTemplateId.HTTP_API_BASICS: _HttpApiBasicsTemplate(),
            GenerationTemplateId.DATA_TRANSFORM_BASICS: _DataTransformBasicsTemplate(),
        }

    def select(
        self,
        user_prompt: str,
        target_audience: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> GenerationTemplateSelectionResult:
        """
        Score templates by keyword frequency and return the best match.

        Falls back to PYTHON_BASICS (safe default) if no keywords match.
        Ties are broken by _SELECTION_PRECEDENCE order.
        """
        normalized = user_prompt.lower()
        scores: dict[GenerationTemplateId, int] = {
            tid: _score(normalized, _COMPILED_PATTERNS[tid])
            for tid in GenerationTemplateId
        }
        best_score = max(scores.values())

        if best_score == 0:
            return GenerationTemplateSelectionResult(
                selected_template_id=GenerationTemplateId.PYTHON_BASICS,
                warnings=["no keyword match found; using PYTHON_BASICS as safe default"],
            )

        for tid in _SELECTION_PRECEDENCE:
            if scores[tid] == best_score:
                return GenerationTemplateSelectionResult(selected_template_id=tid)

        # unreachable, but satisfy type checker
        return GenerationTemplateSelectionResult(
            selected_template_id=GenerationTemplateId.PYTHON_BASICS
        )

    def get_by_id(self, template_id: GenerationTemplateId) -> GenerationTemplate:
        return self._templates[template_id]

    def list_all(self) -> list[GenerationTemplate]:
        return list(self._templates.values())
