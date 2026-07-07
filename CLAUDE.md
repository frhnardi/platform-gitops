# CLAUDE.md — platform-gitops

## What this repo is

The desired state of the cluster, reconciled by **ArgoCD**, and the **enforcement layer**: Kyverno policies that make the golden path mandatory. If it isn't declared here, it doesn't run in the cluster; if it wasn't built by the golden path, the cluster rejects it.

## Layout

```
apps/                  # ArgoCD Application manifests (app-of-apps root: apps/root.yaml)
clusters/dev/          # cluster-scoped config: argocd bootstrap, namespaces
policies/baseline/     # pod security: no privileged, no :latest, resource limits required,
                       # runAsNonRoot, drop ALL capabilities, readOnlyRootFilesystem
policies/supply-chain/ # verify-image-signature.yaml, verify-sbom-attestation.yaml
exceptions/            # Kyverno PolicyException resources (each with expiry)
```

## Non-negotiable constraints

- **Kyverno, not Gatekeeper** (ADR-0004). Do not introduce Rego.
- **`verifyImages` is the keystone** (ADR-0005): admit only images signed keyless by the golden-path workflow identity:
  - issuer: `https://token.actions.githubusercontent.com`
  - subject regex pinned to the golden-path reusable workflow ref.
  - `mutateDigest: true`, `verifyDigest: true` — tags are rewritten to digests at admission.
- Baseline policies run in `Enforce` mode in app namespaces, `Audit` in `kube-system`/platform namespaces. Never flip a policy from Enforce to Audit to "fix" a deployment — that is what `exceptions/` is for.
- **Every PolicyException must have**: a `spec` scoped to one policy + one workload (no wildcards), an `expires` annotation (ISO date, max 30 days out), a `reason` annotation, and a linked issue/PR. CI must fail if an exception lacks expiry or is already expired.
- **Denial messages are product copy.** Every `validate.message` must follow: what was rejected → why it matters → exact remediation → doc link. Example: `"Image is not signed by the golden path. Unsigned images can't be traced to a reviewed build. Ship via the golden-path pipeline: https://github.com/<org>/platform-golden-path#quickstart"`.

## Conventions

- Plain Kubernetes YAML + Kustomize overlays. **No Helm charts authored in this repo** (consuming upstream charts for ArgoCD/Kyverno via ArgoCD is fine).
- Policy tests with **Kyverno Chainsaw** live next to each policy (`*_test/` folder): at minimum one "good resource admitted" and one "bad resource rejected" case per rule. A policy without a test does not merge.
- ArgoCD: app-of-apps pattern, `syncPolicy.automated` with `prune: true, selfHeal: true` for platform apps; app workloads sync automatically but prune manually.
- All third-party manifests pinned by version/digest.

## Workflow for Claude Code

1. Plan mode first. Policy changes have blast radius — describe which workloads a change would newly reject.
2. After editing a policy, run its Chainsaw test; after editing kustomizations, run `kustomize build` on every overlay.
3. Never weaken the supply-chain policies' identity matching (broadening the subject regex) without an ADR amendment.

## Definition of done (Phases 3–4)

- ArgoCD bootstrapped via app-of-apps; Kyverno installed and healthy.
- Demo assertions pass: unsigned image → rejected with actionable message; golden-path image → admitted with digest pinned; expired exception → CI fails.
