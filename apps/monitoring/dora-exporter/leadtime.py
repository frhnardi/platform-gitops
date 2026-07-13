"""Pure DORA lead-time / deployment-frequency logic for the exporter.

Deliberately free of any Kubernetes or Prometheus client imports so the whole
decision surface can be unit-tested without a cluster (see test_leadtime.py).
exporter.py is the thin shell that feeds live Deployment objects through here.

The two DORA signals this module derives:
  * Lead time for changes  — git commit -> pods serving the new revision.
  * Deployment frequency   — one data point per completed rollout of a new sha.

t0 (the commit) and the sha come from annotations the golden-path promotion PR
stamps onto the workload; t1 (serving) is the Deployment's Available condition
transition time. Both are facts the cluster already records — nothing is faked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# Annotations the golden-path promotion PR writes onto the service kustomization
# (as commonAnnotations). The commit timestamp is the "t0" of lead-time-for-changes.
COMMIT_TS_ANNOTATION = "paved-road.platform/commit-timestamp"
COMMIT_SHA_ANNOTATION = "paved-road.platform/commit-sha"


@dataclass(frozen=True)
class DeploymentEvent:
    """One completed rollout worth recording as a DORA data point."""

    service: str
    namespace: str
    commit_sha: str
    lead_time_seconds: float
    ready_at: datetime


def parse_timestamp(value: str) -> datetime:
    """Parse an RFC 3339 / ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' (Kubernetes emits it; datetime.fromisoformat rejected
    it before Python 3.11) and treats a naive string as already-UTC.
    """
    if not value:
        raise ValueError("empty timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def available_condition_time(conditions) -> Optional[datetime]:
    """Return when the Deployment last became Available (=True), else None.

    That transition is the moment the new ReplicaSet's pods were actually
    serving — the "running pod" end of the lead-time measurement.
    """
    for cond in conditions or []:
        if cond.get("type") == "Available" and cond.get("status") == "True":
            ltt = cond.get("lastTransitionTime")
            if ltt:
                return parse_timestamp(ltt)
    return None


def rollout_complete(spec_replicas, generation, status) -> bool:
    """True only when the *current* generation is fully rolled out.

    Guards against reading a half-finished rollout: observedGeneration must have
    caught up to the spec generation, and every desired replica must be updated
    and available with none unavailable. Reading lead time mid-rollout would
    record a number that keeps changing.
    """
    if not status:
        return False
    if (status.get("observedGeneration") or 0) < (generation or 0):
        return False
    desired = spec_replicas or 0
    updated = status.get("updatedReplicas") or 0
    available = status.get("availableReplicas") or 0
    unavailable = status.get("unavailableReplicas") or 0
    return (
        desired > 0
        and updated == desired
        and available == desired
        and unavailable == 0
    )


def compute_lead_time(commit_ts: datetime, ready_ts: datetime) -> Optional[float]:
    """Seconds from commit to serving; None if the interval is negative.

    A negative delta means clock skew or a mislabelled annotation — dropping it
    is better than polluting the histogram with an impossible value.
    """
    delta = (ready_ts - commit_ts).total_seconds()
    return delta if delta >= 0 else None


def should_emit(previous_sha: Optional[str], current_sha: Optional[str]) -> bool:
    """Emit a data point only when a *new* commit sha has rolled out.

    Re-observing the same sha every poll would inflate deployment frequency and
    re-add the same lead time — so we record a rollout exactly once.
    """
    return bool(current_sha) and current_sha != previous_sha


def evaluate_deployment(deployment, previous_sha) -> Optional[DeploymentEvent]:
    """Turn a Deployment (raw API dict) into a DeploymentEvent, or None.

    Returns an event only when: the workload carries both golden-path annotations,
    the sha differs from what we last recorded, the current generation is fully
    rolled out, and the resulting lead time is non-negative.
    """
    meta = deployment.get("metadata", {}) or {}
    spec = deployment.get("spec", {}) or {}
    status = deployment.get("status", {}) or {}
    annotations = meta.get("annotations", {}) or {}

    current_sha = annotations.get(COMMIT_SHA_ANNOTATION)
    commit_ts_raw = annotations.get(COMMIT_TS_ANNOTATION)
    if not current_sha or not commit_ts_raw:
        return None
    if not should_emit(previous_sha, current_sha):
        return None
    if not rollout_complete(spec.get("replicas"), meta.get("generation"), status):
        return None

    ready_at = available_condition_time(status.get("conditions"))
    if ready_at is None:
        return None

    lead = compute_lead_time(parse_timestamp(commit_ts_raw), ready_at)
    if lead is None:
        return None

    return DeploymentEvent(
        service=meta.get("name", "unknown"),
        namespace=meta.get("namespace", "default"),
        commit_sha=current_sha,
        lead_time_seconds=lead,
        ready_at=ready_at,
    )
