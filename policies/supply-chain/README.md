# Supply-chain policies — the keystone (ADR-0005)

Two `ClusterPolicy` resources that make the golden path mandatory. Baseline
policies harden *how* a Pod runs; these decide *whether it runs at all*, based
on provenance:

| Policy | Requires |
|---|---|
| [verify-image-signature](verify-image-signature.yaml) | a keyless cosign **signature** from the golden-path workflow identity |
| [verify-sbom-attestation](verify-sbom-attestation.yaml) | a keyless **SPDX SBOM attestation** from the same identity |

## The pinned identity

Both policies admit only images whose signature/attestation certificate was
issued to the golden-path reusable workflow:

- **issuer:** `https://token.actions.githubusercontent.com` (GitHub Actions OIDC)
- **subject:** `https://github.com/<ORG>/platform-golden-path/.github/workflows/golden-path.yml@refs/heads/main`

This is the whole security claim (ADR-0005): not "signed with our key" but
"provably produced by the reviewed pipeline." The subject regex is
security-critical — **never broaden it without an ADR-0005 amendment**
(`CLAUDE.md`). `rekor.url` verifies the Rekor transparency-log inclusion.

## How each policy works (two rules)

Kyverno 1.18 cannot attach a custom message to a blocking `verifyImages` rule —
a failed verification is denied inside the mutation webhook with a fixed
technical string ("no signatures found" / "subject mismatch"), and it also
forbids `mutateDigest: true` on a non-blocking (Audit) rule. Since denial
messages are product copy in this repo, each policy splits the work:

1. **`verify-*` (verifyImages, Audit):** verifies the signature/attestation and
   records the per-image verdict in the `kyverno.io/verify-images` annotation
   (`"pass"` / `"fail"`). Does not block by itself.
2. **`require-*` (validate, Enforce):** denies admission whenever any image
   carries a `"fail"` verdict — with the full four-part message ending in the
   golden-path quickstart link.

The annotation is shared across all verifyImages rules and is `"fail"` if *any*
of them failed the image (verified empirically on 1.18.1) — so the deny
condition is fail-closed across both policies.

**Trade-off accepted (deliberate, user-approved):** `mutateDigest`/`verifyDigest`
are off, so Kyverno does not rewrite tags to digests at admission. In practice
the golden path already deploys by digest — the promotion PR into this repo
writes image *digests*, never tags — and [disallow-latest-tag](../baseline/disallow-latest-tag.yaml)
blocks the mutable-tag footgun. If Kyverno later allows custom messages on
blocking verifyImages rules, revisit and turn digest mutation back on.

## Scope and failure mode

- Matched to app-tier namespaces only (`namespaceSelector: paved-road.platform/tier=app`).
  Platform images (argocd, kyverno) are not golden-path builds and must never be
  seen by these rules.
- `failurePolicy: Fail`, `webhookTimeoutSeconds: 30`: verification calls out to
  Rekor/Fulcio; if Kyverno itself is unreachable the request is rejected. The
  keystone fails closed.

## How it's tested

Keyless identity is tied to real Sigstore infrastructure and real OIDC issuers,
so a golden-path signature can't be minted locally. The Chainsaw suite therefore:

- Runs the **rejection** cases against the **real shipping policies**: an
  unsigned image (`busybox`) and a validly-signed-but-wrong-identity image
  (`ghcr.io/kyverno/zulu`, signed by `chipzoller/zulu`) are both rejected, and
  each denial is asserted to carry the golden-path quickstart link. The
  wrong-identity case is the one that proves the design.
- Runs the **admit** cases against **stand-in policies** pinned to that same
  real public image, proving a correctly-verified image is admitted with a
  `"pass"` verdict recorded. The stand-ins are structurally identical to
  production — only the pinned identity (and SBOM format: zulu publishes
  CycloneDX, the golden path publishes SPDX) differs. See each
  `*-admit_test/policy.yaml`.

```sh
make test-policies      # includes the wrong-identity rejection
```

Once Phase 2 has published a real golden-path-signed image, the production
policies admit it unchanged — no test rewrite needed.
