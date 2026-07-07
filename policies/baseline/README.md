# Baseline pod-security policies

Six Kyverno `ClusterPolicy` resources that harden every Pod on the golden path.
They are the floor: privileged mode off, images pinned, resources bounded,
non-root, no ambient capabilities, immutable root filesystem.

## Enforcement model

Each rule is `failureAction: Audit` by default and overrides to **Enforce** for
namespaces carrying the label `paved-road.platform/tier: app`:

```yaml
validate:
  failureAction: Audit
  failureActionOverrides:
    - action: Enforce
      namespaceSelector:
        matchLabels:
          paved-road.platform/tier: app
```

So a violation in the `apps` namespace is **rejected at admission**; the same
violation in a platform namespace (`argocd`, `kyverno`, `kube-system`) is
**recorded in a PolicyReport but admitted**. That is deliberate — see
[`CLAUDE.md`](../../CLAUDE.md) ("Enforce in app namespaces, Audit in platform
namespaces"). The namespace labels are set in
[`clusters/dev/namespaces/`](../../clusters/dev/namespaces).

To loosen enforcement for a specific workload, do **not** flip a policy to Audit
— add a scoped, expiring `PolicyException` under [`exceptions/`](../../exceptions).

## Running the tests

Each policy ships with a Chainsaw test in its `*_test/` folder (one admitted
pod, one rejected pod). The test namespace is labelled `tier: app` so the
Enforce override applies.

```sh
make test-policies      # kind up -> pinned Kyverno -> chainsaw -> tear down
```

## The controls

The denial messages link here. Each section is what the platform requires and
the exact field to set.

### Disallow privileged containers

A privileged container disables isolation — every capability plus raw host
device access — so compromising it compromises the node. Never set
`securityContext.privileged: true`. If you need one kernel privilege, drop all
capabilities and add back just that one.

```yaml
securityContext:
  privileged: false
```

### Pin image tags (no :latest)

`:latest` (and an untagged image, which resolves to `:latest`) is a moving
target: the cluster can't tell you which build is running and can't reproduce an
incident. Pin an explicit version — better, ship through the golden path, which
rewrites tags to immutable digests at build time and is what the supply-chain
policy verifies.

```yaml
# not: app:latest  /  app
image: registry.example.com/app:1.4.2
```

### Require resource limits

Without limits, one workload can consume the whole node: a memory leak triggers
node-wide OOM kills, a CPU spike throttles every neighbour. Every container
declares CPU **and** memory limits (add matching requests so the scheduler can
bin-pack).

```yaml
resources:
  requests: { cpu: 10m, memory: 32Mi }
  limits:   { cpu: 500m, memory: 256Mi }
```

### Run as non-root

A process running as UID 0 in the container is UID 0 on the host if it escapes
the sandbox. Require `runAsNonRoot: true` at the pod level (or on every
container). Add `runAsUser` if the image defaults to root.

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
```

### Drop all capabilities

Containers start with a set of Linux capabilities (`NET_RAW`, `CHOWN`, `SETUID`,
…) an attacker can abuse after a compromise. Drop them all and add back only
what's justified.

```yaml
securityContext:
  capabilities:
    drop: ["ALL"]
    # add: ["NET_BIND_SERVICE"]   # only if you truly bind a low port
```

### Read-only root filesystem

A writable rootfs lets an attacker drop a binary or install persistence inside
the running container. Make the image immutable at runtime and mount explicit
volumes for the paths your app writes.

```yaml
securityContext:
  readOnlyRootFilesystem: true
volumeMounts:
  - { name: tmp, mountPath: /tmp }
volumes:
  - { name: tmp, emptyDir: {} }
```
