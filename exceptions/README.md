# PolicyExceptions — the escape hatch

A policy blocked your deploy and you can't get compliant today. The answer is
**never** to weaken a policy (Enforce → Audit is prohibited — `CLAUDE.md`); the
answer is a `PolicyException`: scoped to exactly one policy and one workload,
expiring in at most 30 days, with a written reason and a linked issue. Reviewed
like code, because it is code.

## How to request one

1. Copy the [example below](#a-valid-exception) into `exceptions/<workload>-<policy>.yaml`.
2. Add the file to [`kustomization.yaml`](kustomization.yaml) (that's what ships it).
3. Open a PR using the exception template:
   append `?template=exception.md` to the compare URL, or pick *exception* in
   the template chooser. Fill in every field.
4. A platform reviewer approves; ArgoCD deploys it to the `kyverno` namespace.
   Kyverno only honors exceptions from that namespace — nobody can hand-apply
   one somewhere else.

## The contract (enforced by CI)

Every exception in this directory must have:

| Requirement | Detail |
|---|---|
| **One policy** | exactly one `spec.exceptions[]` entry, `policyName` + explicit `ruleNames` — no wildcards |
| **One workload** | `spec.match.any` with exactly one filter: one `kind`, one `name`, one `namespace` — no wildcards, no missing `names` |
| **`paved-road.platform/expires`** | ISO date `YYYY-MM-DD`, at most 30 days from now. The exception stops counting on that date — plan removal *before* it |
| **`paved-road.platform/reason`** | non-empty: why the workload can't comply *yet* |
| **`paved-road.platform/issue`** | link to the issue/PR tracking the path back to compliance |
| **`metadata.namespace: kyverno`** | the only namespace Kyverno accepts exceptions from |

## What gets rejected

CI ([`scripts/validate_exceptions.py`](../scripts/validate_exceptions.py), run
on every PR) fails the build with a pointed message when it finds:

- **Wildcards anywhere** — `*` or `?` in `policyName`, `ruleNames`, `kinds`,
  `names`, or `namespaces`. A wildcard exception is a policy deletion in disguise.
- **Scope creep** — more than one policy, more than one workload filter, or a
  missing `names` list (which silently means "every workload of that kind").
- **`expires` more than 30 days out, malformed, or missing.** Need longer?
  Renew with a fresh PR and a fresh review.
- **An expired exception still in the repo.** Expiry means *removal*, not
  decoration: delete the file (ArgoCD prunes it from the cluster) or renew it
  deliberately. CI stays red until you do.
- **Empty/missing `reason` or `issue`.**

Run the same check locally: `make test-exceptions`.

## A valid exception

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: checkout-api-readonly-rootfs
  namespace: kyverno
  annotations:
    paved-road.platform/expires: "2026-07-20"
    paved-road.platform/reason: >-
      checkout-api writes its JIT cache to /var/cache at startup; fix (emptyDir
      mount) is merged but blocked on the v1.9 release train.
    paved-road.platform/issue: https://github.com/frhnardi/checkout-api/issues/142
spec:
  exceptions:
    - policyName: require-readonly-rootfs
      ruleNames:
        # Deployments are matched by the autogen'd rule — prefix with autogen-.
        # For a bare Pod the rule name would be validate-readonly-rootfs.
        - autogen-validate-readonly-rootfs
  match:
    any:
      - resources:
          kinds:
            - Deployment
          names:
            - checkout-api
          namespaces:
            - apps
```

## Lifecycle

Granting is cheap and temporary; keeping is expensive and deliberate. When the
`expires` date arrives, the file is deleted (ArgoCD's `prune: true` removes it
from the cluster) and the workload either complies or gets blocked again. There
is no silent renewal — a renewal is a new PR, a new reason, and a new review.

`fixtures/` contains deliberately-invalid exceptions used by the CI check's own
tests. They are **not** in `kustomization.yaml` and never reach the cluster.
