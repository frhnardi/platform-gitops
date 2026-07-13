"""DORA exporter — turns completed rollouts into Prometheus metrics.

Thin I/O shell around leadtime.py: it polls Deployments in the app namespace,
runs each through the pure evaluation logic, and records a data point the first
time a new commit sha is fully rolled out. All decision logic lives in
leadtime.py (and is unit-tested there); keep this file boring on purpose.

Metrics exposed on :8080/metrics
  dora_deployment_lead_time_seconds{service,namespace}      histogram (commit -> serving)
  dora_deployments_total{service,namespace}                 counter   (deployment frequency)
  dora_last_lead_time_seconds{service,namespace}            gauge     (most recent, for single-stat)
  dora_last_deployment_timestamp_seconds{service,namespace} gauge     (unix ts of last rollout)
"""

import json
import logging
import os
import time

from kubernetes import client, config
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from leadtime import evaluate_deployment

NAMESPACE = os.environ.get("DORA_NAMESPACE", "apps")
METRICS_PORT = int(os.environ.get("DORA_METRICS_PORT", "8080"))
POLL_INTERVAL = int(os.environ.get("DORA_POLL_INTERVAL_SECONDS", "30"))

# Buckets span a realistic commit->pod path: a few minutes of CI, plus merge and
# ArgoCD sync. 30s to 4h, so an elite (<1h) vs slow lead time is legible on a heatmap.
LEAD_TIME = Histogram(
    "dora_deployment_lead_time_seconds",
    "Seconds from source commit to the new revision serving (DORA lead time for changes).",
    ["service", "namespace"],
    buckets=(30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400),
)
DEPLOYMENTS = Counter(
    "dora_deployments_total",
    "Completed rollouts of a new commit (DORA deployment frequency).",
    ["service", "namespace"],
)
LAST_LEAD_TIME = Gauge(
    "dora_last_lead_time_seconds",
    "Lead time of the most recent rollout, for single-stat panels.",
    ["service", "namespace"],
)
LAST_DEPLOY_TS = Gauge(
    "dora_last_deployment_timestamp_seconds",
    "Unix timestamp of the most recent completed rollout.",
    ["service", "namespace"],
)


def load_kube_config():
    """In-cluster when running as a pod; fall back to local kubeconfig for dev."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def fetch_deployments(apps_api, namespace):
    """Return Deployments as raw API dicts (camelCase, string timestamps).

    _preload_content=False hands back the untouched API JSON, which is exactly
    the shape leadtime.py models — no client-object-to-dict translation to drift.
    """
    resp = apps_api.list_namespaced_deployment(namespace, _preload_content=False)
    return json.loads(resp.data).get("items", [])


def poll_once(apps_api, seen, emit):
    """One reconcile pass. `emit=False` primes `seen` without recording (see main)."""
    for dep in fetch_deployments(apps_api, NAMESPACE):
        meta = dep.get("metadata", {})
        key = (meta.get("namespace"), meta.get("name"))
        event = evaluate_deployment(dep, seen.get(key))
        if event is None:
            continue
        if emit:
            LEAD_TIME.labels(event.service, event.namespace).observe(event.lead_time_seconds)
            DEPLOYMENTS.labels(event.service, event.namespace).inc()
            LAST_LEAD_TIME.labels(event.service, event.namespace).set(event.lead_time_seconds)
            LAST_DEPLOY_TS.labels(event.service, event.namespace).set(event.ready_at.timestamp())
            logging.info(
                "recorded deployment service=%s sha=%s lead_time=%.0fs",
                event.service, event.commit_sha[:12], event.lead_time_seconds,
            )
        seen[key] = event.commit_sha


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_kube_config()
    apps_api = client.AppsV1Api()
    start_http_server(METRICS_PORT)
    logging.info("DORA exporter serving :%d, watching namespace %s every %ds",
                 METRICS_PORT, NAMESPACE, POLL_INTERVAL)

    # Prime on the first pass so a restart does not re-count rollouts that already
    # happened. The cost is missing a deployment that landed while we were down —
    # an acceptable trade for a lab, and it keeps the frequency counter honest.
    seen = {}
    poll_once(apps_api, seen, emit=False)
    logging.info("primed %d workload(s); recording from here", len(seen))

    while True:
        try:
            poll_once(apps_api, seen, emit=True)
        except Exception:  # noqa: BLE001 — a transient API error must not kill the loop
            logging.exception("poll failed; retrying next interval")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
