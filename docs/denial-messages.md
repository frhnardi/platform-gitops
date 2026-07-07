# Denial messages are product copy

The admission denial is the highest-traffic page your platform will ever ship.
Nobody reads the policy repo; everybody reads the error that just blocked their
deploy at 4:55 on a Friday. That error either teaches — *here's what happened,
here's why we care, here's the one thing you do next* — or it stonewalls, and
the developer routes around your platform instead of through it.

Compare what Kyverno says out of the box:

> `failed to verify image docker.io/library/busybox:1.36.1:
> .attestors[0].entries[0].keyless: no signatures found`

with what this cluster says:

> `This image is not signed by the golden path, so the cluster can't prove it
> came from a reviewed, policy-gated build — and it will not run code of
> unknown provenance. … Ship it through the paved road:
> https://github.com/<ORG>/platform-golden-path#quickstart`

Same rejection. One is a stack trace; the other is a signpost. That difference
is the whole adoption strategy of a paved road: **the guardrail must point at
the road.**

## The rule

Every `validate.message` in this repo must carry four parts, in order
(`CLAUDE.md`):

1. **What** was rejected — the exact field or behavior, named.
2. **Why** it matters — the incident this prevents, not "policy violation".
3. **Fix** — copy-pasteable: the field, a sane value, an example.
4. **Link** — one click to the guide with the full story.

## The audit

Method: swept all 11 rules across the 8 shipped `ClusterPolicy` resources
(from `kustomize build policies`, i.e. exactly what ArgoCD deploys), judged
each message part-by-part, and mechanically verified that every embedded link's
anchor exists in the target README's actual headings.

| Policy / rule | Denial message (verbatim) | What | Why | Fix | Link | Verdict |
|---|---|:-:|:-:|:-:|:-:|---|
| `disallow-privileged` / `privileged-containers` | Privileged containers are not allowed: a container in this Pod sets securityContext.privileged: true. Privileged mode disables container isolation — it hands the container every Linux capability plus raw host device access, so one compromised process becomes a compromised node. Remove the field (or set securityContext.privileged: false) and, if you genuinely need a kernel privilege, add back only that one capability under securityContext.capabilities.add. Guide: …/policies/baseline/README.md#disallow-privileged-containers | ✅ | ✅ | ✅ | ✅ | **Pass** (opening clause tightened during this audit) |
| `disallow-latest-tag` / `require-image-tag` | Image reference has no tag, so it resolves to :latest. An untagged image can't be reproduced or rolled back — two deploys minutes apart may run different code. Pin an explicit version, e.g. registry.example.com/app:1.4.2. Better: ship through the golden path, which rewrites tags to immutable digests at build time. Guide: …/policies/baseline/README.md#pin-image-tags-no-latest | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `disallow-latest-tag` / `disallow-latest-tag` | Image uses the mutable :latest tag. :latest points at a moving target, so the cluster can't tell you which build is actually running and can't reproduce an incident. Pin an explicit version tag (e.g. app:1.4.2), or ship through the golden path, which pins images by digest. Guide: …/policies/baseline/README.md#pin-image-tags-no-latest | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `require-resource-limits` / `validate-resource-limits` | Container is missing resources.limits.cpu and/or resources.limits.memory. Without limits a workload can consume the whole node — a memory leak triggers node-wide OOM kills and CPU spikes throttle every neighbour, turning one bad pod into a cluster incident. Set both, for example: resources.limits.cpu: 500m and resources.limits.memory: 256Mi (and a matching requests block so the scheduler can bin-pack). Guide: …/policies/baseline/README.md#require-resource-limits | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `require-run-as-nonroot` / `run-as-non-root` | Container may run as root: runAsNonRoot: true is not set at the pod or container level. A process running as UID 0 inside the container is UID 0 on the host if it ever escapes the sandbox, so root-in-container removes the last safety margin behind any container breakout. Set spec.securityContext.runAsNonRoot: true for the whole pod (add runAsUser: 65532 if the image defaults to root), or set it on every container's securityContext. Guide: …/policies/baseline/README.md#run-as-non-root | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `drop-all-capabilities` / `require-drop-all` | Container does not drop ALL capabilities: securityContext.capabilities.drop must contain "ALL". Containers start with a set of Linux capabilities (NET_RAW, CHOWN, SETUID and more) that an attacker can use to sniff traffic, forge packets, or bypass file permissions after a compromise. Drop everything and add back only what you need: securityContext.capabilities.drop: ["ALL"] (then, if required, capabilities.add: ["NET_BIND_SERVICE"]). Guide: …/policies/baseline/README.md#drop-all-capabilities | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `require-readonly-rootfs` / `validate-readonly-rootfs` | Container has a writable root filesystem: securityContext.readOnlyRootFilesystem is not set to true. A writable rootfs lets an attacker who lands code execution drop a binary, patch a config, or install a persistence mechanism that survives inside the running container. Set securityContext.readOnlyRootFilesystem: true and mount an emptyDir (or a real volume) for the specific paths your app must write, e.g. /tmp or a cache dir. Guide: …/policies/baseline/README.md#read-only-root-filesystem | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `verify-image-signature` / `require-golden-path-signature` | This image is not signed by the golden path, so the cluster can't prove it came from a reviewed, policy-gated build — and it will not run code of unknown provenance. Every image must be built and pushed by the golden-path pipeline, which signs it keyless with the workflow's GitHub OIDC identity (issuer token.actions.githubusercontent.com, subject &lt;ORG&gt;/platform-golden-path/.github/workflows/golden-path.yml@refs/heads/main). Ship it through the paved road: https://github.com/&lt;ORG&gt;/platform-golden-path#quickstart | ✅ | ✅ | ✅ | ✅ | **Pass** |
| `verify-sbom-attestation` / `require-golden-path-sbom` | This image has no SPDX SBOM attestation signed by the golden path, so the cluster can't see what's inside it — no bill of materials means no way to answer "are we affected?" when the next CVE lands. The golden-path pipeline generates an SPDX SBOM with Syft and attaches it as a keyless-signed attestation (cosign attest --type spdx). Ship it through the paved road: https://github.com/&lt;ORG&gt;/platform-golden-path#quickstart | ✅ | ✅ | ✅ | ✅ | **Pass** |

**Result: 9/9 shipped messages pass all four parts. Every link's anchor
verified against the target README** (`#quickstart` resolves in
platform-golden-path; all six baseline anchors resolve in
policies/baseline/README.md).

## The two rules that carry no message — deliberately

`verify-golden-path-signature` and `verify-golden-path-sbom` (the `verifyImages`
halves of the supply-chain policies) have no `validate.message`, and can't:
Kyverno 1.18 attaches a fixed technical string to blocking image-verification
failures and offers no custom-copy hook there. That is exactly why each
supply-chain policy is two rules — the `verifyImages` rule verifies and records
the verdict in Audit, and its paired Enforce `validate` rule (audited above) is
the only voice the developer ever hears. Design + trade-offs:
[policies/supply-chain/README.md](../policies/supply-chain/README.md).

## Out of scope

The `*_test/policy.yaml` stand-ins carry one-line messages ("stand-in: image
not signed by the expected identity."). They exist only inside throwaway test
clusters, are excluded from every kustomization, and never speak to a human at
deploy time — exempt.

## Keeping it honest

- The supply-chain Chainsaw tests assert the quickstart link is present in the
  actual denial an apiserver returns — the copy is pinned by CI, not by intent.
- The baseline anchors live in `policies/baseline/README.md` headings. If you
  rename a heading, the messages pointing at it are now lying: re-run this
  audit's anchor check (see git history of this file) before merging.
- New policy? Its message doesn't merge without all four parts. Write it like
  the person reading it is blocked, annoyed, and one bad error message away
  from bypassing your platform — because they are.
