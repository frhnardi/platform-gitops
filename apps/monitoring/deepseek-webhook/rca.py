"""Pure alert-RCA helpers — prompt building and config checks.

No FastAPI/httpx imports so the prompt logic is unit-testable without the web
stack or network (see test_rca.py). app.py wires these into the HTTP handler.
"""

from __future__ import annotations

DEFAULT_MAX_ALERTS = 5
PLACEHOLDER_KEY = "placeholder-set-your-key"


def summarize_alert(alert: dict) -> str:
    """One-alert summary block for the LLM prompt. Tolerant of missing fields."""
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    summary = annotations.get("summary") or labels.get("alertname") or "unknown"
    description = (annotations.get("description") or "N/A")[:500]
    return (
        f"Alert: {summary}\n"
        f"  Severity: {labels.get('severity', 'unknown')}\n"
        f"  Namespace: {labels.get('namespace', 'N/A')}\n"
        f"  Description: {description}"
    )


def build_prompt(alerts, max_alerts: int = DEFAULT_MAX_ALERTS) -> str:
    """Assemble the SRE root-cause prompt from up to `max_alerts` alerts."""
    summaries = "\n".join(summarize_alert(a) for a in alerts[:max_alerts])
    return (
        "You are a Site Reliability Engineer analyzing Kubernetes monitoring alerts.\n"
        "Provide root cause analysis and actionable remediation steps for these alerts:\n\n"
        f"{summaries}\n\n"
        "Format your response as:\n"
        "1. **Root Cause Analysis**: What likely caused these alerts\n"
        "2. **Impact Assessment**: What's affected\n"
        "3. **Remediation Steps**: Specific kubectl/helm commands to fix\n"
        "4. **Prevention**: How to prevent recurrence\n"
    )


def api_key_configured(key: str) -> bool:
    """True only for a real key — empty or the committed placeholder is 'unset'."""
    return bool(key) and key != PLACEHOLDER_KEY
