# DORA exporter

Turns completed rollouts into two DORA signals, measured from facts the cluster
already records — nothing is simulated:

| Metric | Type | Meaning |
|---|---|---|
| `dora_deployment_lead_time_seconds{service,namespace}` | histogram | git commit → the new revision serving (**lead time for changes**) |
| `dora_deployments_total{service,namespace}` | counter | completed rollouts of a new commit (**deployment frequency**) |
| `dora_last_lead_time_seconds{service,namespace}` | gauge | most recent lead time (for single-stat panels) |
| `dora_last_deployment_timestamp_seconds{service,namespace}` | gauge | unix ts of the last rollout |

## How lead time is measured (honestly)

The number is `t1 − t0`:

- **t0 — the commit.** The golden-path promotion PR stamps two annotations onto
  the service's kustomization (as `commonAnnotations`), which land on the
  Deployment: `paved-road.platform/commit-sha` and
  `paved-road.platform/commit-timestamp` (the git author-commit time).
- **t1 — serving.** The Deployment's `Available=True` condition transition time,
  i.e. when the new ReplicaSet's pods were actually ready.

So lead time is *your real commit* to *a real running pod* — through CI, image
signing, the promotion PR merge, and the ArgoCD sync. No estimate, no stopwatch.

## Design notes worth knowing

- **A rollout is recorded once.** The exporter only emits when a *new* commit sha
  reaches a *fully* rolled-out state (`observedGeneration` caught up, every
  replica updated and available). Reading mid-rollout would log a moving number.
- **Restarts don't double-count.** On start the exporter *primes* — it reads the
  current shas without recording them — so a pod restart can't re-inflate the
  deployment counter. The trade-off (a deploy that lands while the exporter is
  down is missed) is acceptable for a lab and keeps the counter trustworthy.
- **Clock-skew guard.** A negative interval (commit stamped after serving) is
  dropped rather than poisoning the histogram.

All of that logic lives in `leadtime.py`, kept free of Kubernetes/Prometheus
imports so it is unit-tested without a cluster.

## Test

```bash
pip install pytest
pytest              # 23 cases over the pure logic
```

## Build & deploy

Built and signed through the golden path like any other service; the manifest
(`../dora-exporter.yaml`) pins the image by digest and reads Deployments in the
`apps` namespace via a read-only ClusterRole. Prometheus scrapes
`dora-exporter.monitoring:8080` (see `../prometheus.yaml`), and the
**Platform Engineering** Grafana dashboard renders the DORA row.

See ADR-0011 for the decision and its trade-offs.
