<!-- PolicyException request — every field is required. CI enforces most of
     this mechanically (scripts/validate_exceptions.py); reviewers enforce the
     rest. See exceptions/README.md for the contract and a valid example. -->

## What is blocked

- **Workload** (one — kind/name/namespace): <!-- e.g. Deployment/checkout-api in apps -->
- **Policy + rule(s)** (one policy): <!-- e.g. require-readonly-rootfs / autogen-validate-readonly-rootfs -->
- **Denial message you hit**: <!-- paste it -->

## Why compliance isn't possible right now

<!-- The real reason, not "it doesn't work". This becomes the
     paved-road.platform/reason annotation. -->

## Path back to compliance

- **Tracking issue/PR** (required, becomes the `issue` annotation):
- **Planned fix**: <!-- what change makes the exception unnecessary -->
- **Expires** (`YYYY-MM-DD`, max 30 days out): <!-- removal is scheduled for this date, not renewal -->

## Checklist

- [ ] Exactly one policy and one workload — no wildcards anywhere
- [ ] `paved-road.platform/expires` set, ≤ 30 days from today
- [ ] `paved-road.platform/reason` and `paved-road.platform/issue` set
- [ ] `metadata.namespace: kyverno`
- [ ] File added to `exceptions/kustomization.yaml`
- [ ] I understand expiry means the file gets **deleted** — renewal is a new PR
