"""Unit tests for the pure RCA helpers. No web stack or network needed."""

from rca import PLACEHOLDER_KEY, api_key_configured, build_prompt, summarize_alert


def test_summarize_prefers_annotations_summary():
    alert = {"labels": {"alertname": "HighMem", "severity": "warning", "namespace": "apps"},
             "annotations": {"summary": "Memory high on sample-service",
                             "description": "working set > 90% for 5m"}}
    out = summarize_alert(alert)
    assert "Memory high on sample-service" in out
    assert "Severity: warning" in out
    assert "Namespace: apps" in out
    assert "working set > 90% for 5m" in out


def test_summarize_falls_back_to_alertname_and_defaults():
    out = summarize_alert({"labels": {"alertname": "PodCrashLoop"}})
    assert "Alert: PodCrashLoop" in out
    assert "Severity: unknown" in out
    assert "Namespace: N/A" in out
    assert "Description: N/A" in out


def test_summarize_truncates_long_description():
    alert = {"annotations": {"summary": "x", "description": "y" * 999}}
    out = summarize_alert(alert)
    assert "y" * 500 in out
    assert "y" * 501 not in out


def test_build_prompt_caps_alert_count():
    alerts = [{"labels": {"alertname": f"A{i}"}} for i in range(10)]
    prompt = build_prompt(alerts, max_alerts=3)
    assert "A0" in prompt and "A2" in prompt
    assert "A3" not in prompt
    assert "Root Cause Analysis" in prompt
    assert "Remediation Steps" in prompt


def test_api_key_configured():
    assert api_key_configured("sk-real-key")
    assert not api_key_configured("")
    assert not api_key_configured(PLACEHOLDER_KEY)
