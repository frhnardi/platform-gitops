# Bootstrap — one-time cluster install

Everything in this cluster is reconciled from git by ArgoCD. The commands below
are the **only** imperative steps: they install ArgoCD and hand it the app-of-apps
root. After that, nothing is applied by hand — Kyverno, policies, and workloads
all arrive through GitOps. If you find yourself running `kubectl apply` for
anything else, stop: it belongs in git.

## Prerequisites

- `kubectl` pointed at the target dev cluster (`kubectl config current-context`).
- This repo pushed to `https://github.com/frhnardi/platform-gitops` on branch `main`.
- In [`apps/root.yaml`](../apps/root.yaml), replace `frhnardi` in `repoURL` with your
  GitHub org. ArgoCD pulls the repo over git; it does not read your local files.

## Steps

```sh
# 1. Namespaces (argocd must exist before ArgoCD is installed into it).
kubectl apply -k clusters/dev/namespaces

# 2. Install ArgoCD — pinned to v3.4.4, image pinned by digest.
kubectl apply -k clusters/dev/argocd

# 3. Wait until the control plane is up.
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

# 4. Hand off to GitOps: apply the app-of-apps root. It reconciles apps/,
#    which brings in Kyverno and everything after it.
kubectl apply -f apps/root.yaml
```

That's the whole bootstrap. Kyverno appears because `apps/kyverno.yaml` is in the
directory `root` watches — not because you installed it.

## Verify

```sh
# ArgoCD picked up the root app and its children (root, kyverno, ...).
kubectl -n argocd get applications

# Kyverno reconciled into its namespace.
kubectl -n kyverno get pods
```

## Accessing the ArgoCD UI (optional)

```sh
# Initial admin password (delete the secret once you've set up real access).
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo

# Port-forward the API/UI to localhost:8080.
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

## Upgrading ArgoCD

ArgoCD bootstraps itself but does not upgrade itself here. Bump the pin in
[`clusters/dev/argocd/kustomization.yaml`](../clusters/dev/argocd/kustomization.yaml)
(both the version tag in the resource URL and the image digest), then re-run
step 2. Every other component upgrades through git alone.
