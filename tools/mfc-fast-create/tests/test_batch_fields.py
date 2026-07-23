import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import BatchItem, _build_custom_parameters, _validate_extra_fields  # noqa: E402


def _item(**kwargs):
    base = dict(
        title="t",
        object_id=1,
        typical="Консультация",
        solution="Самовосстановление",
    )
    base.update(kwargs)
    return BatchItem(**base)


def test_custom_params_with_complication_and_n():
    item = _item(
        complication_level="+15",
        complication="долго искали причину в БД",
        object_count="3",
    )
    assert _validate_extra_fields(item) is None
    p = _build_custom_parameters(item)
    assert p["complication_level"] == "+15"
    assert p["complication"] == "долго искали причину в БД"
    assert p["object_count"] == "3"
    assert p["solution_method"] == ["Самовосстановление"]


def test_complication_requires_pair():
    assert _validate_extra_fields(_item(complication_level="+30")) is not None
    assert _validate_extra_fields(_item(complication="текст")) is not None


def test_object_count_must_be_digits():
    assert _validate_extra_fields(_item(object_count="12a")) is not None
    assert _validate_extra_fields(_item(object_count="0")) is not None
