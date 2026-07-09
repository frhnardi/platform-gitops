# platform-gitops — policy test harness.
#
# `make test-policies` spins up a throwaway kind cluster, installs the same
# pinned Kyverno the cluster runs, and runs the Chainsaw suite that lives next
# to each policy. Everything is pinned; bump versions here deliberately.

# ---- Pinned toolchain (keep KYVERNO_CHART_VERSION == apps/kyverno.yaml) --------
KYVERNO_CHART_VERSION ?= 3.8.1
KYVERNO_REPO          ?= https://kyverno.github.io/kyverno/
CHAINSAW_VERSION      ?= v0.2.15
KIND_VERSION          ?= v0.32.0
# Mature, lighter node image (kind v0.32.0 also ships v1.36.1, but that is heavy
# and flaky to bootstrap on cgroup v1 / low-memory hosts like WSL2).
KIND_NODE_IMAGE       ?= kindest/node:v1.33.12@sha256:3f5c8443c620245e4d355cfe09e96a91ead32ceaa569d3f1ca9edf0cb2fe2ff4

CLUSTER_NAME ?= paved-road-policies
KEEP_CLUSTER ?= 0

# ---- Local, pinned tools (downloaded on demand, never from PATH) --------------
LOCALBIN := $(CURDIR)/.tools/bin
KIND     := $(LOCALBIN)/kind
CHAINSAW := $(LOCALBIN)/chainsaw
OS       := $(shell uname -s | tr '[:upper:]' '[:lower:]')
ARCH     := $(shell uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')
export PATH := $(LOCALBIN):$(PATH)

KUSTOMIZE_PATHS := clusters/dev/namespaces clusters/dev/argocd policies policies/baseline policies/supply-chain exceptions

.DEFAULT_GOAL := help
.PHONY: help tools kind-up kind-down kyverno-install test-policies test-exceptions build clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

$(LOCALBIN):
	mkdir -p $(LOCALBIN)

$(KIND): | $(LOCALBIN)
	curl -fsSL -o $(KIND) https://github.com/kubernetes-sigs/kind/releases/download/$(KIND_VERSION)/kind-$(OS)-$(ARCH)
	chmod +x $(KIND)

$(CHAINSAW): | $(LOCALBIN)
	curl -fsSL https://github.com/kyverno/chainsaw/releases/download/$(CHAINSAW_VERSION)/chainsaw_$(OS)_$(ARCH).tar.gz \
	  | tar -xz -C $(LOCALBIN) chainsaw
	chmod +x $(CHAINSAW)

tools: $(KIND) $(CHAINSAW) ## Download the pinned kind + chainsaw binaries into .tools/bin
	@$(KIND) version
	@$(CHAINSAW) version

test-exceptions: ## Unit-test the exception validator, then validate exceptions/
	python3 -m unittest discover -s scripts
	python3 scripts/validate_exceptions.py exceptions

build: ## kustomize build every overlay (fails on any broken kustomization)
	@for d in $(KUSTOMIZE_PATHS); do \
	  printf '== kustomize build %s ==\n' "$$d"; \
	  kubectl kustomize "$$d" >/dev/null || exit 1; \
	done
	@echo "all kustomizations build clean"

kind-up: $(KIND) ## Create the kind cluster if it does not already exist
	@if $(KIND) get clusters 2>/dev/null | grep -qx $(CLUSTER_NAME); then \
	  echo "cluster $(CLUSTER_NAME) already exists"; \
	else \
	  for attempt in 1 2 3; do \
	    echo ">> kind create cluster (attempt $$attempt/3)"; \
	    $(KIND) create cluster --name $(CLUSTER_NAME) --image "$(KIND_NODE_IMAGE)" --wait 180s && break; \
	    echo ">> attempt $$attempt failed; cleaning up before retry"; \
	    $(KIND) delete cluster --name $(CLUSTER_NAME) >/dev/null 2>&1 || true; \
	    [ $$attempt -eq 3 ] && { echo ">> kind create failed after 3 attempts"; exit 1; } || sleep 5; \
	  done; \
	fi
	kubectl config use-context kind-$(CLUSTER_NAME)

kind-down: $(KIND) ## Delete the kind cluster
	-$(KIND) delete cluster --name $(CLUSTER_NAME)

kyverno-install: ## Install the pinned Kyverno chart into the kind cluster
	helm repo add kyverno $(KYVERNO_REPO) --force-update
	helm repo update kyverno
	# Test harness runs only the admission controller — the chainsaw suite
	# exercises admission enforcement, not background scans / reports / cleanup.
	# (The cluster itself, via apps/kyverno.yaml, runs the full set.)
	helm upgrade --install kyverno kyverno/kyverno \
	  --version $(KYVERNO_CHART_VERSION) \
	  --namespace kyverno --create-namespace \
	  --set features.policyExceptions.enabled=true \
	  --set features.policyExceptions.namespace=kyverno \
	  --set admissionController.replicas=1 \
	  --set backgroundController.enabled=false \
	  --set cleanupController.enabled=false \
	  --set reportsController.enabled=false \
	  --wait --timeout 5m
	kubectl wait --for=condition=established --timeout=90s crd/clusterpolicies.kyverno.io

test-policies: tools ## kind up -> install kyverno -> run chainsaw suite -> tear down
	@$(MAKE) kind-up
	@$(MAKE) kyverno-install
	@status=0; \
	 $(CHAINSAW) test policies --parallel 1 || status=$$?; \
	 if [ "$(KEEP_CLUSTER)" != "1" ]; then $(MAKE) kind-down; fi; \
	 exit $$status

clean: kind-down ## Delete the cluster and the downloaded tools
	rm -rf $(CURDIR)/.tools
