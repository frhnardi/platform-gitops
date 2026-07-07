# platform-gitops

Desired state of the cluster (ArgoCD app-of-apps) and the enforcement layer (Kyverno). Only images keyless-signed by the golden-path workflow identity are admitted; every policy ships with Chainsaw tests; exceptions expire.

See [`CLAUDE.md`](CLAUDE.md). ADRs live in `platform-infra/docs/adr/`.

Status: Phases 3–4 — pending Phase 2.
