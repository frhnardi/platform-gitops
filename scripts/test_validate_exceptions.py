"""Unit tests for validate_exceptions.py.

Run: python3 -m unittest discover -s scripts   (or: make test-exceptions)
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

import validate_exceptions as ve

TODAY = date(2026, 7, 6)
REPO_ROOT = Path(__file__).resolve().parents[1]
EXPIRED_FIXTURE = REPO_ROOT / "exceptions" / "fixtures" / "expired-example.yaml"


def valid_doc(expires: str = "2026-07-20") -> dict:
    """A PolicyException that satisfies the whole contract (expires TODAY+14)."""
    return {
        "apiVersion": "kyverno.io/v2",
        "kind": "PolicyException",
        "metadata": {
            "name": "checkout-api-readonly-rootfs",
            "namespace": "kyverno",
            "annotations": {
                ve.EXPIRES_KEY: expires,
                ve.REASON_KEY: "JIT cache writes to /var/cache; fix blocked on v1.9.",
                ve.ISSUE_KEY: "https://github.com/org/checkout-api/issues/142",
            },
        },
        "spec": {
            "exceptions": [
                {
                    "policyName": "require-readonly-rootfs",
                    "ruleNames": ["autogen-validate-readonly-rootfs"],
                }
            ],
            "match": {
                "any": [
                    {
                        "resources": {
                            "kinds": ["Deployment"],
                            "names": ["checkout-api"],
                            "namespaces": ["apps"],
                        }
                    }
                ]
            },
        },
    }


class ValidDocument(unittest.TestCase):
    def test_valid_exception_passes(self):
        self.assertEqual(ve.validate_document(valid_doc(), "x.yaml", TODAY), [])

    def test_expiry_exactly_30_days_out_passes(self):
        doc = valid_doc((TODAY + timedelta(days=30)).isoformat())
        self.assertEqual(ve.validate_document(doc, "x.yaml", TODAY), [])


class ExpiryRules(unittest.TestCase):
    def assert_single_error(self, doc: dict, fragment: str):
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(fragment, errors[0])

    def test_expired_fails(self):
        self.assert_single_error(valid_doc("2026-06-15"), "expiry means removal")

    def test_expires_today_counts_as_expired(self):
        self.assert_single_error(valid_doc(TODAY.isoformat()), "expiry means removal")

    def test_31_days_out_fails(self):
        doc = valid_doc((TODAY + timedelta(days=31)).isoformat())
        self.assert_single_error(doc, "maximum is 30")

    def test_missing_expires_fails(self):
        doc = valid_doc()
        del doc["metadata"]["annotations"][ve.EXPIRES_KEY]
        self.assert_single_error(doc, ve.EXPIRES_KEY)

    def test_non_iso_date_fails(self):
        self.assert_single_error(valid_doc("20 July 2026"), "not an ISO date")

    def test_on_disk_expired_fixture_fails(self):
        """The deliberately-expired fixture must trip exactly the expiry check."""
        doc = yaml.safe_load(EXPIRED_FIXTURE.read_text())
        errors = ve.validate_document(doc, str(EXPIRED_FIXTURE), TODAY)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("expired on 2026-06-15", errors[0])


class AnnotationRules(unittest.TestCase):
    def test_blank_reason_fails(self):
        doc = valid_doc()
        doc["metadata"]["annotations"][ve.REASON_KEY] = "   "
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertTrue(any(ve.REASON_KEY in e for e in errors), errors)

    def test_missing_issue_fails(self):
        doc = valid_doc()
        del doc["metadata"]["annotations"][ve.ISSUE_KEY]
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertTrue(any(ve.ISSUE_KEY in e for e in errors), errors)


class ScopeRules(unittest.TestCase):
    def assert_error_containing(self, doc: dict, fragment: str):
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_wildcard_workload_name_fails(self):
        doc = valid_doc()
        doc["spec"]["match"]["any"][0]["resources"]["names"] = ["checkout-*"]
        self.assert_error_containing(doc, "wildcard")

    def test_wildcard_kind_fails(self):
        doc = valid_doc()
        doc["spec"]["match"]["any"][0]["resources"]["kinds"] = ["*"]
        self.assert_error_containing(doc, "wildcard")

    def test_wildcard_namespace_fails(self):
        doc = valid_doc()
        doc["spec"]["match"]["any"][0]["resources"]["namespaces"] = ["app?"]
        self.assert_error_containing(doc, "wildcard")

    def test_wildcard_policy_name_fails(self):
        doc = valid_doc()
        doc["spec"]["exceptions"][0]["policyName"] = "require-*"
        self.assert_error_containing(doc, "wildcard")

    def test_wildcard_rule_name_fails(self):
        doc = valid_doc()
        doc["spec"]["exceptions"][0]["ruleNames"] = ["autogen-*"]
        self.assert_error_containing(doc, "wildcard")

    def test_missing_names_fails(self):
        doc = valid_doc()
        del doc["spec"]["match"]["any"][0]["resources"]["names"]
        self.assert_error_containing(doc, "names")

    def test_two_policies_fails(self):
        doc = valid_doc()
        doc["spec"]["exceptions"].append(copy.deepcopy(doc["spec"]["exceptions"][0]))
        self.assert_error_containing(doc, "exactly one policy")

    def test_two_workload_filters_fails(self):
        doc = valid_doc()
        doc["spec"]["match"]["any"].append(
            copy.deepcopy(doc["spec"]["match"]["any"][0])
        )
        self.assert_error_containing(doc, "exactly one workload")

    def test_match_all_fails(self):
        doc = valid_doc()
        doc["spec"]["match"] = {"all": doc["spec"]["match"]["any"]}
        self.assert_error_containing(doc, "match.any")

    def test_selector_fails(self):
        doc = valid_doc()
        doc["spec"]["match"]["any"][0]["resources"]["selector"] = {
            "matchLabels": {"app": "checkout"}
        }
        self.assert_error_containing(doc, "selector")


class IdentityRules(unittest.TestCase):
    def test_wrong_namespace_fails(self):
        doc = valid_doc()
        doc["metadata"]["namespace"] = "default"
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertTrue(any("kyverno" in e for e in errors), errors)

    def test_wrong_kind_fails(self):
        doc = valid_doc()
        doc["kind"] = "ConfigMap"
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("PolicyException resources only", errors[0])

    def test_wrong_api_version_fails(self):
        doc = valid_doc()
        doc["apiVersion"] = "kyverno.io/v2beta1"
        errors = ve.validate_document(doc, "x.yaml", TODAY)
        self.assertTrue(any("kyverno.io/v2" in e for e in errors), errors)


class TreeWalk(unittest.TestCase):
    def test_fixtures_and_kustomization_skipped_live_files_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fixtures").mkdir()
            # A blatantly bad exception hidden in fixtures/ must NOT be checked.
            (root / "fixtures" / "bad.yaml").write_text(
                yaml.safe_dump({"kind": "PolicyException", "metadata": {}})
            )
            (root / "kustomization.yaml").write_text(
                yaml.safe_dump(
                    {
                        "apiVersion": "kustomize.config.k8s.io/v1beta1",
                        "kind": "Kustomization",
                        "resources": [],
                    }
                )
            )
            (root / "ok.yaml").write_text(yaml.safe_dump(valid_doc()))
            errors, checked = ve.validate_tree(root, TODAY)
            self.assertEqual(errors, [])
            self.assertEqual(checked, 1)

    def test_wildcard_exception_in_live_dir_fails_actionably(self):
        """The acceptance case: a wildcard exception must fail with a message
        that names the file, the problem, and the fix."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = valid_doc()
            doc["spec"]["match"]["any"][0]["resources"]["names"] = ["*"]
            (root / "sneaky.yaml").write_text(yaml.safe_dump(doc))
            errors, checked = ve.validate_tree(root, TODAY)
            self.assertEqual(checked, 1)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("sneaky.yaml", errors[0])
            self.assertIn("wildcard", errors[0])
            self.assertIn("Name exactly one target", errors[0])

    def test_missing_directory_reports_error(self):
        errors, checked = ve.validate_tree(Path("/nonexistent-dir"), TODAY)
        self.assertEqual(checked, 0)
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
