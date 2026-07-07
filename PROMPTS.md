# Claude Code Prompts — platform-gitops (Phases 3–4)

Prerequisite: Phase 2 done (at least one signed image with SBOM attestation exists in ACR). Paste in order, plan mode first.

---

## Prompt 3.1 — ArgoCD bootstrap (app-of-apps)

```
Read CLAUDE.md first. Create the bootstrap layer:
1. clusters/dev/: namespace manifests (argocd, kyverno, apps) and an install kustomization for ArgoCD pinned to a specific version/digest.
2. apps/root.yaml: the app-of-apps Application watching apps/ in this repo.
3. apps/kyverno.yaml: Application deploying Kyverno from its official chart, pinned version, into the kyverno namespace, with automated sync + prune + selfHeal (platform app policy per CLAUDE.md).
4. A short docs/bootstrap.md: the exact one-time kubectl commands a human runs to install ArgoCD and apply root.yaml, and nothing else — everything after that is GitOps.
Acceptance: kustomize build clean on every path; all images/charts pinned.
```

## Prompt 3.2 — Baseline policies + Chainsaw tests

```
Implement policies/baseline/ per CLAUDE.md: disallow-privileged, disallow-latest-tag, require-resource-limits, require-run-as-nonroot, drop-all-capabilities, require-readonly-rootfs. Enforce mode, scoped to the apps namespace via namespaceSelector; Audit elsewhere.
Every validate.message must follow the four-part format in CLAUDE.md (what/why/fix/link) — treat the messages as product copy, write them carefully.
For EACH policy create a Chainsaw test with one admitted and one rejected manifest.
Wire an ArgoCD Application for policies. Add a GitHub Actions workflow running chainsaw test + kustomize build on PR.
Acceptance: all Chainsaw tests pass locally against a kind cluster (include a make target: make test-policies spins up kind + kyverno + runs chainsaw).
```

## Prompt 3.3 — Supply-chain enforcement (the keystone)

```
Implement policies/supply-chain/verify-image-signature.yaml per ADR-0005:
- verifyImages, Enforce, apps namespace
- attestors: keyless, issuer https://token.actions.githubusercontent.com, subject regexp pinned EXACTLY to frhnardi/platform-golden-path/.github/workflows/golden-path.yml@refs/heads/main
- mutateDigest: true, verifyDigest: true, required: true
Also verify-sbom-attestation.yaml requiring the SPDX attestation from the same identity.
Chainsaw tests: signed image admitted, unsigned rejected, image signed by a DIFFERENT workflow identity rejected (this third case is the one that proves the design — do not skip it).
The denial message must include the golden-path quickstart link.
Acceptance: make test-policies green including the wrong-identity case.
```

## Prompt 4.1 — Exception workflow

```
Implement the escape hatch per CLAUDE.md:
1. exceptions/README.md: how to request an exception (PR template), what gets rejected (wildcards, >30 days, no reason).
2. .github/PULL_REQUEST_TEMPLATE/exception.md with required fields.
3. A CI check (script + workflow) that validates every PolicyException in exceptions/: single policy + single workload scope, expires annotation present, ISO-8601, <= 30 days from now, reason annotation non-empty. CI fails on any expired exception still present in the repo — expiry means removal, not decoration.
4. One example exception (expired on purpose, in a fixtures/ dir excluded from the live kustomization) used by the CI check's own tests.
Acceptance: the check script has unit tests; a PR adding a wildcard exception fails CI with an actionable message.
```

## Prompt 4.2 — Denial-message audit

```
Sweep every policy in this repo and audit each validate.message against the four-part rule (what/why/fix/link). Produce a table in docs/denial-messages.md listing every policy, its message, and status. Fix any message that fails. This doc doubles as LinkedIn post material — write the messages like you mean them.
```
