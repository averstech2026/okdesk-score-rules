import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parser import parse_list  # noqa: E402
from fuzzy import suggest_typical, score_match  # noqa: E402
import json  # noqa: E402

SAMPLE = """
https://help.ucg.ru/Task/View/136419
https://help.ucg.ru/Task/View/136416
Сбер. Оплата
https://help.ucg.ru/Task/View/136425
НК НПЗ. Чек
ПП12. Закрыть смену
ОМК. Клиенты
Маг 15\\1. Закрыть смену
"""

CATALOGS = json.loads((ROOT / "catalogs.json").read_text(encoding="utf-8"))


def test_parse_sample_from_docs23():
    rows = parse_list(SAMPLE)
    assert len(rows) == 8

    assert rows[0].source_type == "url"
    assert rows[0].external_id == "136419"
    assert rows[0].title == "UCG #136419"
    assert rows[0].external_url == "https://help.ucg.ru/Task/View/136419"
    assert rows[0].object_hint is None

    assert rows[2].source_type == "text"
    assert rows[2].title == "Сбер. Оплата"
    assert rows[2].object_hint == "Сбер"
    assert rows[2].typical_hint == "Оплата"

    assert rows[4].object_hint == "НК НПЗ"
    assert rows[4].typical_hint == "Чек"

    assert rows[5].object_hint == "ПП12"
    assert rows[5].typical_hint == "Закрыть смену"

    assert rows[7].object_hint == "Маг 15\\1"
    assert rows[7].typical_hint == "Закрыть смену"


def test_blank_lines_ignored():
    rows = parse_list("a\n\n\nb\n")
    assert [r.title for r in rows] == ["a", "b"]


def test_url_trailing_slash():
    rows = parse_list("https://help.ucg.ru/Task/View/1/")
    assert rows[0].external_id == "1"


def test_intraservice_edit_and_query():
    rows = parse_list(
        "https://help.ucg.ru/Task/Edit/99?foo=1\n"
        "<https://help.ucg.ru/Task/View/88>\n"
        "[тикет](https://help.ucg.ru/Task/View/77)\n"
    )
    assert [r.external_id for r in rows] == ["99", "88", "77"]
    assert all(r.source_type == "url" for r in rows)


def test_url_plus_text_same_line():
    rows = parse_list("https://help.ucg.ru/Task/View/5 ПП12. Смена")
    assert len(rows) == 1
    assert rows[0].external_id == "5"
    assert rows[0].title == "ПП12. Смена"
    assert rows[0].object_hint == "ПП12"


def test_typical_aliases():
    t = suggest_typical(
        "Закрыть смену", CATALOGS["typical"], CATALOGS["typical_aliases"]
    )
    assert t == "Не закрывается смена"
    t2 = suggest_typical("Оплата", CATALOGS["typical"], CATALOGS["typical_aliases"])
    assert t2 == "Не проходит оплата (по банку или процессинг)"


def test_score_backslash_normalize():
    assert score_match("Маг 15/1", "Маг 15\\1") >= 0.85
