#!/usr/bin/env python3
"""Validate every PolicyException in exceptions/ against the contract in
exceptions/README.md (CLAUDE.md: scoped, expiring, justified — or rejected).

Checks, per exception:
  - kyverno.io/v2 PolicyException, metadata.namespace == kyverno
  - exactly one policy (one spec.exceptions[] entry), explicit ruleNames
  - exactly one workload (match.any with one filter: one kind/name/namespace)
  - no wildcards ('*' / '?') anywhere in the scope
  - paved-road.platform/expires: ISO date, in the future, <= 30 days out
    (an expired exception still in the repo FAILS: expiry means removal)
  - paved-road.platform/reason and paved-road.platform/issue: non-empty

fixtures/ is skipped (test data for this script's own tests). Exit 1 on any
violation, with a message that says how to fix it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

ANNOTATION_PREFIX = "paved-road.platform"
EXPIRES_KEY = f"{ANNOTATION_PREFIX}/expires"
REASON_KEY = f"{ANNOTATION_PREFIX}/reason"
ISSUE_KEY = f"{ANNOTATION_PREFIX}/issue"
MAX_DAYS = 30
REQUIRED_NAMESPACE = "kyverno"
EXPECTED_API_VERSION = "kyverno.io/v2"
DOC_LINK = "See exceptions/README.md."
# The only scope keys an exception may use. selector/namespaceSelector broaden
# scope invisibly; operations etc. add nothing a reviewer should reason about.
ALLOWED_RESOURCE_KEYS = {"kinds", "names", "namespaces"}


def _has_wildcard(value: str) -> bool:
    return "*" in value or "?" in value


def _single_explicit(errors: list[str], src: str, field: str, value: object) -> None:
    """Require `value` to be a list of exactly one non-empty, wildcard-free string."""
    if not isinstance(value, list) or len(value) == 0:
        errors.append(
            f"{src}: {field} is missing or empty — an exception must name its scope "
            f"explicitly; omitting it means 'all of them', which is a wildcard in "
            f"disguise. List exactly one entry. {DOC_LINK}"
        )
        return
    if len(value) > 1:
        errors.append(
            f"{src}: {field} lists {len(value)} entries — an exception covers exactly "
            f"one policy and one workload. Split into separate exceptions (each gets "
            f"its own review and expiry). {DOC_LINK}"
        )
    for i, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            errors.append(
                f"{src}: {field}[{i}] is empty or not a string — name it explicitly. {DOC_LINK}"
            )
        elif _has_wildcard(entry):
            errors.append(
                f"{src}: {field}[{i}] is a wildcard ({entry!r}) — a wildcard exception "
                f"is a policy deletion in disguise, so it is rejected. Name exactly one "
                f"target. {DOC_LINK}"
            )


def _check_annotations(errors: list[str], src: str, doc: dict, today: date) -> None:
    annotations = (doc.get("metadata") or {}).get("annotations") or {}

    expires_raw = annotations.get(EXPIRES_KEY)
    if expires_raw is None or not str(expires_raw).strip():
        errors.append(
            f"{src}: missing '{EXPIRES_KEY}' annotation — every exception expires. "
            f"Set an ISO date (YYYY-MM-DD) at most {MAX_DAYS} days out. {DOC_LINK}"
        )
    else:
        try:
            expires = date.fromisoformat(str(expires_raw).strip())
        except ValueError:
            errors.append(
                f"{src}: '{EXPIRES_KEY}: {expires_raw}' is not an ISO date — use "
                f"YYYY-MM-DD, e.g. \"{(today + timedelta(days=14)).isoformat()}\". {DOC_LINK}"
            )
        else:
            if expires <= today:
                errors.append(
                    f"{src}: expired on {expires.isoformat()} (today is {today.isoformat()}) "
                    f"— expiry means removal, not decoration. Delete this file (ArgoCD "
                    f"prunes it from the cluster) or renew it with a fresh PR and a "
                    f"fresh review. {DOC_LINK}"
                )
            elif (expires - today).days > MAX_DAYS:
                errors.append(
                    f"{src}: expires {expires.isoformat()} is {(expires - today).days} days "
                    f"out — the maximum is {MAX_DAYS}. Pick a date on or before "
                    f"{(today + timedelta(days=MAX_DAYS)).isoformat()}; if the fix needs "
                    f"longer, renew later with a fresh review. {DOC_LINK}"
                )

    reason = annotations.get(REASON_KEY)
    if reason is None or not str(reason).strip():
        errors.append(
            f"{src}: missing or empty '{REASON_KEY}' annotation — say why the workload "
            f"can't comply yet; the reviewer (and future you) needs it. {DOC_LINK}"
        )

    issue = annotations.get(ISSUE_KEY)
    if issue is None or not str(issue).strip():
        errors.append(
            f"{src}: missing or empty '{ISSUE_KEY}' annotation — link the issue/PR "
            f"tracking the path back to compliance. No tracked fix, no exception. {DOC_LINK}"
        )


def _check_scope(errors: list[str], src: str, doc: dict) -> None:
    spec = doc.get("spec") or {}

    exceptions = spec.get("exceptions")
    if not isinstance(exceptions, list) or len(exceptions) != 1:
        count = len(exceptions) if isinstance(exceptions, list) else 0
        errors.append(
            f"{src}: spec.exceptions has {count} entries — an exception covers exactly "
            f"one policy. One file per policy, each with its own expiry. {DOC_LINK}"
        )
    else:
        entry = exceptions[0] or {}
        policy_name = entry.get("policyName")
        if not isinstance(policy_name, str) or not policy_name.strip():
            errors.append(
                f"{src}: spec.exceptions[0].policyName is missing — name the one policy "
                f"being excepted. {DOC_LINK}"
            )
        elif _has_wildcard(policy_name):
            errors.append(
                f"{src}: policyName is a wildcard ({policy_name!r}) — excepting "
                f"policies by pattern is rejected. Name exactly one policy. {DOC_LINK}"
            )
        rule_names = entry.get("ruleNames")
        if not isinstance(rule_names, list) or len(rule_names) == 0:
            errors.append(
                f"{src}: spec.exceptions[0].ruleNames is missing or empty — list the "
                f"specific rule(s), e.g. 'autogen-validate-readonly-rootfs' for a "
                f"Deployment. {DOC_LINK}"
            )
        else:
            for i, rule in enumerate(rule_names):
                if not isinstance(rule, str) or not rule.strip():
                    errors.append(f"{src}: ruleNames[{i}] is empty. {DOC_LINK}")
                elif _has_wildcard(rule):
                    errors.append(
                        f"{src}: ruleNames[{i}] is a wildcard ({rule!r}) — list rule "
                        f"names explicitly. {DOC_LINK}"
                    )

    match = spec.get("match") or {}
    if "all" in match:
        errors.append(
            f"{src}: spec.match uses 'all' — exceptions in this repo use 'match.any' "
            f"with exactly one resource filter, so every reviewer reads the same "
            f"shape. {DOC_LINK}"
        )
    filters = match.get("any")
    if not isinstance(filters, list) or len(filters) != 1:
        count = len(filters) if isinstance(filters, list) else 0
        errors.append(
            f"{src}: spec.match.any has {count} resource filters — an exception covers "
            f"exactly one workload. One filter: one kind, one name, one namespace. {DOC_LINK}"
        )
        return

    resources = (filters[0] or {}).get("resources")
    if not isinstance(resources, dict):
        errors.append(
            f"{src}: spec.match.any[0].resources is missing — scope the exception to "
            f"one kind, one name, one namespace. {DOC_LINK}"
        )
        return

    unexpected = sorted(set(resources) - ALLOWED_RESOURCE_KEYS)
    if unexpected:
        errors.append(
            f"{src}: spec.match.any[0].resources uses {', '.join(unexpected)} — only "
            f"kinds/names/namespaces are allowed. Selectors and other matchers widen "
            f"the scope invisibly; name the one workload instead. {DOC_LINK}"
        )
    prefix = "spec.match.any[0].resources"
    _single_explicit(errors, src, f"{prefix}.kinds", resources.get("kinds"))
    _single_explicit(errors, src, f"{prefix}.names", resources.get("names"))
    _single_explicit(errors, src, f"{prefix}.namespaces", resources.get("namespaces"))


def validate_document(doc: dict, src: str, today: date) -> list[str]:
    """Validate one PolicyException document. Returns a list of error strings."""
    errors: list[str] = []

    kind = doc.get("kind")
    if kind != "PolicyException":
        errors.append(
            f"{src}: kind {kind!r} does not belong in exceptions/ — this directory "
            f"holds PolicyException resources only. {DOC_LINK}"
        )
        return errors

    if doc.get("apiVersion") != EXPECTED_API_VERSION:
        errors.append(
            f"{src}: apiVersion {doc.get('apiVersion')!r} — use {EXPECTED_API_VERSION!r} "
            f"(the storage version in Kyverno 1.18). {DOC_LINK}"
        )

    metadata = doc.get("metadata") or {}
    if not str(metadata.get("name") or "").strip():
        errors.append(f"{src}: metadata.name is missing. {DOC_LINK}")
    namespace = metadata.get("namespace")
    if namespace != REQUIRED_NAMESPACE:
        errors.append(
            f"{src}: metadata.namespace is {namespace!r} — Kyverno only honors "
            f"exceptions from the '{REQUIRED_NAMESPACE}' namespace; set "
            f"'namespace: {REQUIRED_NAMESPACE}' explicitly. {DOC_LINK}"
        )

    _check_annotations(errors, src, doc, today)
    _check_scope(errors, src, doc)
    return errors


def validate_tree(root: Path, today: date) -> tuple[list[str], int]:
    """Validate every YAML file under `root`, skipping fixtures/ and
    Kustomization documents. Returns (errors, documents_checked)."""
    errors: list[str] = []
    checked = 0

    if not root.is_dir():
        return [f"{root}: directory not found — run from the repo root."], 0

    files = sorted(
        p
        for pattern in ("*.yaml", "*.yml")
        for p in root.rglob(pattern)
        if "fixtures" not in p.relative_to(root).parts
    )
    for path in files:
        src = str(path)
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError as exc:
            errors.append(f"{src}: not parseable as YAML ({exc}). {DOC_LINK}")
            continue
        for doc in docs:
            if doc is None:
                continue
            if not isinstance(doc, dict):
                errors.append(f"{src}: unexpected non-mapping YAML document. {DOC_LINK}")
                continue
            if doc.get("kind") == "Kustomization":
                continue
            checked += 1
            errors.extend(validate_document(doc, src, today))
    return errors, checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", nargs="?", default="exceptions", help="directory to validate"
    )
    parser.add_argument(
        "--today", type=date.fromisoformat, default=date.today(), help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)

    errors, checked = validate_tree(Path(args.directory), args.today)
    for error in errors:
        print(f"FAIL {error}", file=sys.stderr)
    print(f"{checked} exception(s) checked, {len(errors)} problem(s) found.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
