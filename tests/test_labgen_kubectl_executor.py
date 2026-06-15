"""
kubectl_executor — unit tests.

Coverage areas:
  A. validate_command: allowed commands
  B. validate_command: blocked subcommands
  C. validate_command: blocked patterns (namespaces, output formats, flags)
  D. validate_command: namespace/kubeconfig override blocking
  E. execute(): blocked → CommandResult(allowed=False)
  F. execute(): empty command
"""

from __future__ import annotations

import pytest

from backend.labgen.kubectl_executor import validate_command

pytestmark = pytest.mark.static


# ── A. Allowed commands ───────────────────────────────────────────────────────

class TestValidateCommandAllowed:

    @pytest.mark.parametrize("cmd", [
        "kubectl get configmap my-app-config",
        "kubectl get cm",
        "kubectl describe configmap my-app-config",
        "kubectl create configmap my-app-config --from-literal=env=learning --from-literal=app=k8s-basics",
        "kubectl create secret generic my-app-secret --from-literal=API_TOKEN=demo-token",
        "kubectl create deployment hello-deployment --image=nginx:1.25-alpine --replicas=1",
        "kubectl get deployment hello-deployment",
        "kubectl describe deployment hello-deployment",
        "kubectl get pods",
        "kubectl get pod hello-deployment-abc123",
        "kubectl get events",
        "kubectl delete configmap my-app-config",
        "kubectl delete secret my-app-secret",
        "kubectl delete deployment hello-deployment",
        "kubectl get secret my-app-secret",
        "kubectl get secrets",
        "kubectl get deployments",
        "kubectl get replicasets",
        # output formats: only wide and name are permitted
        "kubectl get pods -o wide",
        "kubectl get pods -o name",
        "kubectl get pods --output=wide",
        "kubectl get pods --output=name",
        "",  # empty is allowed (no-op)
    ])
    def test_allowed(self, cmd):
        allowed, reason = validate_command(cmd)
        assert allowed, f"Expected '{cmd}' to be allowed, got reason: {reason}"
        assert reason == ""


# ── B. Blocked subcommands ────────────────────────────────────────────────────

class TestValidateCommandBlockedSubcommands:

    @pytest.mark.parametrize("cmd", [
        "kubectl exec my-pod -- bash",
        "kubectl exec -it my-pod -- sh",
        "kubectl port-forward pod/my-pod 8080:80",
        "kubectl proxy",
        "kubectl attach my-pod",
        "kubectl cp my-pod:/etc/config ./local",
        "kubectl debug my-pod",
        "kubectl run test-pod --image=busybox",
        "kubectl plugin list",
    ])
    def test_blocked_subcommand(self, cmd):
        allowed, reason = validate_command(cmd)
        assert not allowed, f"Expected '{cmd}' to be blocked"
        assert reason


# ── C. Blocked patterns ───────────────────────────────────────────────────────

class TestValidateCommandBlockedPatterns:

    @pytest.mark.parametrize("cmd", [
        # config subcommand
        "kubectl config view",
        "kubectl config get-contexts",
        # SA token creation
        "kubectl create token lab-learner",
        # auth
        "kubectl auth can-i create configmap",
        # cluster-scoped resources
        "kubectl get namespaces",
        "kubectl get namespace default",
        "kubectl get nodes",
        "kubectl get node pve",
        "kubectl get clusterroles",
        "kubectl get clusterrolebindings",
        "kubectl delete namespace lab-xxx",
        "kubectl describe clusterrole lab-verifier",
        # all-namespaces flags
        "kubectl get pods --all-namespaces",
        "kubectl get pods -A",
        # raw output formats — space-separated
        "kubectl get secret my-app-secret -o yaml",
        "kubectl get configmap my-app-config -o json",
        "kubectl get deployment hello -o yaml",
        "kubectl get pods --output=yaml",
        "kubectl get pods --output=json",
        # output format bypass variants (jsonpath, go-template, equals-sign, no-space)
        "kubectl get secret my-app-secret -o=yaml",
        "kubectl get secret my-app-secret -o=json",
        "kubectl get secret my-app-secret -oyaml",
        "kubectl get secret my-app-secret -ojson",
        "kubectl get secret my-app-secret -o jsonpath='{.data.password}'",
        "kubectl get secret my-app-secret -o go-template='{{.data.password}}'",
        "kubectl get secret my-app-secret --output yaml",
        "kubectl get secret my-app-secret --output json",
        "kubectl get secret my-app-secret --output=jsonpath='{.data}'",
        # apply from URL
        "kubectl apply -f https://raw.githubusercontent.com/example/repo/main/file.yaml",
    ])
    def test_blocked_pattern(self, cmd):
        allowed, reason = validate_command(cmd)
        assert not allowed, f"Expected '{cmd}' to be blocked"
        assert reason


# ── D. Namespace/kubeconfig override blocking ─────────────────────────────────

class TestValidateCommandOverrideBlocking:

    @pytest.mark.parametrize("cmd", [
        "kubectl get pods --kubeconfig=/etc/kubernetes/admin.conf",
        "kubectl get pods -n default",
        "kubectl get pods --namespace kube-system",
    ])
    def test_blocked_override(self, cmd):
        allowed, reason = validate_command(cmd)
        assert not allowed, f"Expected '{cmd}' to be blocked"
        assert reason


# ── E. Non-kubectl input ──────────────────────────────────────────────────────

class TestValidateCommandNonKubectl:

    @pytest.mark.parametrize("cmd", [
        "ls -la",
        "cat /etc/passwd",
        "curl http://metadata.internal/latest/meta-data/",
        "bash -i",
        "python3 -c 'import os; os.system(\"id\")'",
        "helm install my-release my-chart",
        "k9s",
    ])
    def test_non_kubectl_blocked(self, cmd):
        allowed, reason = validate_command(cmd)
        assert not allowed
        assert "Only kubectl" in reason


# ── F. Edge cases ─────────────────────────────────────────────────────────────

class TestValidateCommandEdgeCases:

    def test_empty_command(self):
        allowed, reason = validate_command("")
        assert allowed
        assert reason == ""

    def test_whitespace_only(self):
        allowed, reason = validate_command("   ")
        assert allowed

    def test_unclosed_quote(self):
        # shlex.split raises ValueError for unclosed quotes
        allowed, reason = validate_command("kubectl create configmap test --from-literal=key='unclosed")
        assert not allowed
        assert "parse" in reason.lower() or "Cannot" in reason

    def test_kubectl_with_no_subcommand(self):
        # "kubectl" alone — should be allowed (no dangerous subcommand)
        allowed, reason = validate_command("kubectl")
        assert allowed
