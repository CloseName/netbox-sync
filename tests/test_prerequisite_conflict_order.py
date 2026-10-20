"""Prerequisite conflict precedence and bounded diagnostic ordering."""

import pytest
from netbox_sync.prerequisites import reconcile
from tests.test_prerequisite_preparation import row


def test_all_definition_conflicts_keep_original_order_without_lifecycle_detail():
    fields = reconcile(
        [
            row(
                "sync_identities",
                type="text",
                object_types=[],
                required=True,
                unique=0,
                validation_minimum=0,
                validation_maximum=0,
                validation_regex="secret",
                validation_schema={"secret": 1},
                status="deleting",
            )
        ]
    )
    first = fields[0]
    assert first["differences"] == [
        "type",
        "models",
        "required",
        "unique",
        "validation_minimum",
        "validation_maximum",
        "validation_regex",
        "validation_schema",
    ]
    assert [item["property"] for item in first["mismatch_details"]] == first["differences"]
    assert "secret" not in str(first)
    assert first["status"] == "conflict"


def test_duplicate_definition_avoids_interpreting_ambiguous_fields():
    bad = row("sync_identities", type=None, object_types=1)
    first = reconcile([None, bad, bad])[0]
    assert first["differences"] == ["duplicate"]
    assert first["id"] is None
    assert first["mismatch_details"] == [{"property": "duplicate", "expected": "1", "actual": "2"}]


@pytest.mark.parametrize("identifier,expected", [(True, None), (0, None), (-1, None), (2, 2)])
def test_field_id_requires_exact_positive_integer(identifier, expected):
    first = reconcile([row("sync_identities", index=identifier)])[0]
    assert first["status"] == "ready"
    assert first["id"] == expected
