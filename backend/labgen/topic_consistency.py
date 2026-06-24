"""
Article-lab topic consistency checker (G-60).

Rule-based, zero LLM. Returns a warning when article title / URL keywords
don't match the lab's target_domain. Mismatch is a soft warning — not a
publish-blocker — because title wording varies and the checker cannot
understand semantics.
"""

from __future__ import annotations

from typing import Optional

# Keywords expected in article title for each domain.
# All checks are case-insensitive.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "linux": [
        "linux", "文件", "权限", "chmod", "shell", "bash",
        "terminal", "命令行", "目录", "permission", "file",
    ],
    "k8s": [
        "kubernetes", "k8s", "pod", "deployment", "configmap",
        "secret", "service", "ingress", "namespace", "helm",
        "容器", "集群", "部署",
    ],
}


def check_article_lab_consistency(
    target_domain: Optional[str],
    article_title: Optional[str],
    article_url: Optional[str],
) -> Optional[str]:
    """Return a warning string if article topic may not match lab domain, else None.

    Returns None when:
    - domain is unknown (no keywords defined)
    - article_title and article_url are both absent (nothing to check)
    - at least one keyword matches

    Returns a warning string when:
    - domain has defined keywords AND title/url are present but contain none of them
    """
    if not target_domain:
        return None

    keywords = _DOMAIN_KEYWORDS.get(target_domain.lower())
    if not keywords:
        return None

    # Build combined text from title and url slug for matching
    parts: list[str] = []
    if article_title:
        parts.append(article_title)
    if article_url:
        parts.append(article_url)

    if not parts:
        return None  # No article bound yet — no mismatch to report

    combined = " ".join(parts).lower()
    if any(kw in combined for kw in keywords):
        return None  # Match found

    matched_domains = [
        domain for domain, kws in _DOMAIN_KEYWORDS.items()
        if domain != target_domain.lower() and any(kw in combined for kw in kws)
    ]

    if matched_domains:
        wrong = ", ".join(matched_domains)
        return (
            f"article title/url appears to match domain '{wrong}' "
            f"but lab target_domain is '{target_domain}'. "
            f"Verify the article topic matches the lab before enabling CTA."
        )

    return (
        f"article title/url contains no recognized keywords for domain '{target_domain}'. "
        f"Verify the article topic matches the lab before enabling CTA."
    )
