"""Unit tests for the pure DORA logic. No cluster required: `pytest` runs it."""

from datetime import datetime, timezone

import pytest

from leadtime import (
    COMMIT_SHA_ANNOTATION,
    COMMIT_TS_ANNOTATION,
    available_condition_time,
    compute_lead_time,
    evaluate_deployment,
    parse_timestamp,
    rollout_complete,
    should_emit,
)


def _dep(sha="abc123", commit_ts="2026-07-13T10:00:00Z", *, generation=2,
         replicas=1, observed=2, updated=1, available=1, unavailable=0,
         available_true="2026-07-13T10:07:30Z", name="sample-service",
         namespace="apps", with_annotations=True):
    """Build a Deployment dict shaped like the real Kubernetes API JSON."""
    annotations = {}
    if with_annotations:
        annotations = {
            COMMIT_SHA_ANNOTATION: sha,
            COMMIT_TS_ANNOTATION: commit_ts,
        }
    conditions = []
    if available_true is not None:
        conditions.append({
            "type": "Available",
            "status": "True",
            "lastTransitionTime": available_true,
        })
    return {
        "metadata": {"name": name, "namespace": namespace,
                     "generation": generation, "annotations": annotations},
        "spec": {"replicas": replicas},
        "status": {
            "observedGeneration": observed,
            "updatedReplicas": updated,
            "availableReplicas": available,
            "unavailableReplicas": unavailable,
            "conditions": conditions,
        },
    }


class TestParseTimestamp:
    def test_z_suffix_is_utc(self):
        assert parse_timestamp("2026-07-13T10:00:00Z") == \
            datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)

    def test_offset_is_normalised_to_utc(self):
        assert parse_timestamp("2026-07-13T17:00:00+07:00") == \
            datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)

    def test_naive_assumed_utc(self):
        assert parse_timestamp("2026-07-13T10:00:00").tzinfo == timezone.utc

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_timestamp("")


class TestAvailableConditionTime:
    def test_returns_available_true_transition(self):
        conds = [{"type": "Progressing", "status": "True",
                  "lastTransitionTime": "2026-07-13T09:00:00Z"},
                 {"type": "Available", "status": "True",
                  "lastTransitionTime": "2026-07-13T10:07:30Z"}]
        assert available_condition_time(conds) == \
            datetime(2026, 7, 13, 10, 7, 30, tzinfo=timezone.utc)

    def test_available_false_is_ignored(self):
        conds = [{"type": "Available", "status": "False",
                  "lastTransitionTime": "2026-07-13T10:00:00Z"}]
        assert available_condition_time(conds) is None

    def test_no_conditions(self):
        assert available_condition_time(None) is None
        assert available_condition_time([]) is None


class TestRolloutComplete:
    def test_fully_rolled_out(self):
        assert rollout_complete(1, 2, {"observedGeneration": 2, "updatedReplicas": 1,
                                       "availableReplicas": 1, "unavailableReplicas": 0})

    def test_stale_observed_generation(self):
        assert not rollout_complete(1, 3, {"observedGeneration": 2, "updatedReplicas": 1,
                                           "availableReplicas": 1, "unavailableReplicas": 0})

    def test_replica_not_yet_available(self):
        assert not rollout_complete(2, 2, {"observedGeneration": 2, "updatedReplicas": 2,
                                           "availableReplicas": 1, "unavailableReplicas": 1})

    def test_zero_replicas_is_not_complete(self):
        assert not rollout_complete(0, 1, {"observedGeneration": 1})


class TestComputeLeadTime:
    def test_positive_interval(self):
        c = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        r = datetime(2026, 7, 13, 10, 7, 30, tzinfo=timezone.utc)
        assert compute_lead_time(c, r) == 450.0

    def test_negative_interval_dropped(self):
        c = datetime(2026, 7, 13, 10, 7, 30, tzinfo=timezone.utc)
        r = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        assert compute_lead_time(c, r) is None


class TestShouldEmit:
    def test_new_sha(self):
        assert should_emit("old", "new")

    def test_same_sha_suppressed(self):
        assert not should_emit("same", "same")

    def test_first_sighting(self):
        assert should_emit(None, "new")

    def test_missing_current(self):
        assert not should_emit("old", None)


class TestEvaluateDeployment:
    def test_happy_path_records_450s(self):
        event = evaluate_deployment(_dep(), previous_sha=None)
        assert event is not None
        assert event.service == "sample-service"
        assert event.namespace == "apps"
        assert event.commit_sha == "abc123"
        assert event.lead_time_seconds == 450.0

    def test_same_sha_returns_none(self):
        assert evaluate_deployment(_dep(sha="abc123"), previous_sha="abc123") is None

    def test_missing_annotations_returns_none(self):
        assert evaluate_deployment(_dep(with_annotations=False), previous_sha=None) is None

    def test_incomplete_rollout_returns_none(self):
        assert evaluate_deployment(_dep(available=0, unavailable=1), previous_sha=None) is None

    def test_not_yet_available_returns_none(self):
        assert evaluate_deployment(_dep(available_true=None), previous_sha=None) is None

    def test_clock_skew_negative_lead_time_returns_none(self):
        # commit stamped AFTER the pod became available -> impossible, dropped.
        skewed = _dep(commit_ts="2026-07-13T11:00:00Z", available_true="2026-07-13T10:07:30Z")
        assert evaluate_deployment(skewed, previous_sha=None) is None
