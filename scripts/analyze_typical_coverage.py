#!/usr/bin/env python3
"""Сравнение текущего typical vs целевой каталог; оценка хвоста на Нестандарт.

Пишет analysis/typical-coverage.json (для typical-final.html / отчётов).
Нужны data/issues/*.json и data/issues_list.jsonl.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "data" / "issues"
OUT = ROOT / "analysis" / "typical-coverage.json"
MFC_IDS = {9}
DOP = "Доп. настройки, сопутствующий сервис, не блокирующий работу"

RULES = [
    ("11", "Карты питания и клиенты", [r"карт", r"лимит", r"дотац", r"клиент", r"сотрудник", r"начислен", r"блокир", r"разблокир"]),
    ("12", "Доступ / код кассира", [r"доступ", r"код", r"кассир", r"парол", r"портал", r"логин", r"учётн", r"учетн", r"\bуз\b"]),
    ("14", "Консультация / звонок", [r"звонок", r"консульт", r"уточн"]),
    ("4", "Корректировка чека", [r"удалить чек", r"удален.*чек", r"сторно", r"возврат", r"отмен.*чек", r"перенос.*чек", r"корректир.*чек"]),
    ("17", "НДС точечный", [r"ставк.*ндс", r"без ндс", r"\bндс\b.*ошиб"]),
    ("22", "Обновление НДС", [r"\bндс\b"]),
    ("1", "Чеки / ФР", [r"чек", r"\bфр\b", r"печат", r"фискал", r"ккт"]),
    ("15a", "Расхождение смены", [r"расхожд.*смен", r"принуд", r"закрыт.*смен", r"открыт.*смен"]),
    ("24", "Расследование", [r"расследован", r"расхожд", r"не бьёт", r"не бьет", r"претензи"]),
    ("15b", "Отчёты", [r"отчет", r"отчёт", r"сверк"]),
    ("3", "Меню / товар", [r"меню", r"товар", r"обмен", r"1[сc]", r"sales3", r"выгрузк"]),
    ("16", "Сопутствующий сервис", [r"work.?bright", r"allbusiness", r"all business", r"ворк.?брайт"]),
    ("21", "Обновление / раскатка ПО", [r"обновл", r"апдейт", r"update", r"раскат", r"спулер", r"spooler", r"frontupdater", r"\bsdk\b", r"лого"]),
    ("10", "ЧЗ оперативный", [r"\bчз\b", r"маркир", r"честн.?ый знак", r"пиот"]),
    ("20", "Запуск / подготовка", [r"запуск", r"подготов", r"моноблок", r"ввод в эксплуат"]),
    ("19", "Оборудование", [r"оборудован", r"подключ", r"установк", r"настрои"]),
    ("18", "Банк / модуль", [r"модул.*банк", r"эквайр", r"банк.*модул"]),
    ("6", "Оплата не проходит", [r"оплат", r"дуэт", r"процессинг", r"терминал"]),
    ("5", "Касса перезапуск", [r"не работает касс", r"перезапуск", r"завис", r"не включа"]),
    ("8", "Сканер / весы", [r"сканер", r"весы"]),
    ("7", "ОФД", [r"\bофд\b"]),
    ("2", "Смена", [r"смен"]),
    ("25", "Статья БЗ", [r"баз[аы] знан", r"стать[яи] бз", r"\bбз\b"]),
    ("13", "Настройки", [r"настрой", r"конфиг", r"тариф", r"планировщик", r"мониторинг"]),
]

ID_NAME = {a: b for a, b, _ in RULES}

NAMED_MAP = {
    "Не печатаются, не закрываются чеки (сбой ФР, сумма оплат меньше/больше чека)": ("1", "Не печатаются / не закрываются чеки…"),
    "Не закрывается смена": ("2", "Не закрывается смена"),
    "Нет меню, нет товара на кассе": ("3", "Нет меню / нет товара"),
    "Отменить чек (сторнирование или возврат средств)": ("4", "Корректировка чека"),
    "Не работает касса, перезапуск на кассе": ("5", "Не работает касса, перезапуск"),
    "Не проходит оплата (по банку или процессинг)": ("6", "Оплата не проходит"),
    "Проблема с оплатой по ДУЭТу": ("6", "Оплата не проходит"),
    "Не уходят чеки в ОФД": ("7", "Не уходят чеки в ОФД"),
    "Не работает сканер, весы": ("8", "Не работает сканер, весы"),
    "Ошибка на кассе (ошибка лицензии, попытка работы задним числом и др)": ("9", "Ошибка на кассе…"),
    "Не работает ЧЗ": ("10", "ЧЗ / маркировка (оперативный)"),
    "Не проходит карта клиента": ("11", "Карты питания и клиенты"),
    "Не обновились лимиты": ("11", "Карты питания и клиенты"),
    "Предоставление доступа": ("12", "Предоставление доступа / код кассира"),
    "Консультация": ("14", "Консультация / звонок"),
    "Вопросы по отчетам": ("15b", "Отчёты"),
    "Не печатается отчет": ("15b", "Отчёты"),
    "Расхождение данных в отчетах с 1С, ОФД и тд.": ("24", "Расхождение / расследование"),
    "Подключение и настройка оборудования": ("19", "Подключение и настройка оборудования"),
}


def classify(title: str) -> str | None:
    t = (title or "").lower()
    for tid, _name, pats in RULES:
        for p in pats:
            if re.search(p, t, re.I):
                return tid
    return None


def param_map(detail: dict) -> dict:
    return {p.get("code"): p.get("value") for p in (detail.get("parameters") or [])}


def main() -> None:
    if not DETAILS.exists():
        raise SystemExit("no data/issues — run fetch_issues.py first")

    buckets = {
        k: {
            "n_all": 0,
            "n_nonmfc": 0,
            "cls_all": Counter(),
            "cls_nonmfc": Counter(),
            "unrec_all": 0,
            "unrec_nonmfc": 0,
        }
        for k in ("Другое", "Доп")
    }
    named_nonmfc: Counter = Counter()
    named_all: Counter = Counter()
    empty_all = empty_nonmfc = 0
    current_all: Counter = Counter()
    current_nonmfc: Counter = Counter()
    unrec_titles: Counter = Counter()
    to_new: Counter = Counter()

    for path in DETAILS.glob("*.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        pm = param_map(d)
        typ = pm.get("typical") or ""
        title = d.get("title") or ""
        is_mfc = d.get("company_id") in MFC_IDS
        typ_key = typ if typ else "(пусто)"
        current_all[typ_key] += 1
        if not is_mfc:
            current_nonmfc[typ_key] += 1

        if not typ:
            empty_all += 1
            if not is_mfc:
                empty_nonmfc += 1
            continue

        if typ in ("Другое", DOP):
            key = "Другое" if typ == "Другое" else "Доп"
            b = buckets[key]
            b["n_all"] += 1
            if not is_mfc:
                b["n_nonmfc"] += 1
            cid = classify(title)
            if cid:
                b["cls_all"][cid] += 1
                to_new[cid] += 0 if is_mfc else 1
                if not is_mfc:
                    b["cls_nonmfc"][cid] += 1
            else:
                b["unrec_all"] += 1
                if not is_mfc:
                    b["unrec_nonmfc"] += 1
                    unrec_titles[title.strip()[:100] or "(без заголовка)"] += 1
            continue

        nid, _ = NAMED_MAP.get(typ, ("OTHER", typ))
        named_all[nid] += 1
        if not is_mfc:
            named_nonmfc[nid] += 1
            if nid != "OTHER":
                to_new[nid] += 1

    # fix to_new for baskets (already added non-mfc above for classified)
    for key in buckets:
        for nid, n in buckets[key]["cls_nonmfc"].items():
            # already counted in loop for non-mfc classify — wait we did to_new[cid]+=1 only in classify branch
            pass

    basket_n = buckets["Другое"]["n_nonmfc"] + buckets["Доп"]["n_nonmfc"]
    basket_cls = sum(buckets["Другое"]["cls_nonmfc"].values()) + sum(buckets["Доп"]["cls_nonmfc"].values())
    basket_unrec = buckets["Другое"]["unrec_nonmfc"] + buckets["Доп"]["unrec_nonmfc"]
    named_cov = sum(v for k, v in named_nonmfc.items() if k != "OTHER")
    nonmfc = sum(current_nonmfc.values())

    old_to_new = []
    for old, n in current_nonmfc.most_common():
        if old == "(пусто)":
            dest = "заполнять из каталога; KPI без пусто"
        elif old == "Другое":
            dest = "разнести по каталогу; хвост → Нестандарт"
        elif old == DOP:
            dest = "сузить → №13 + разнести (карты, раскатки, запуски…)"
        elif old in NAMED_MAP:
            dest = f"→ №{NAMED_MAP[old][0]} {NAMED_MAP[old][1]}"
        else:
            dest = "?"
        old_to_new.append({"old": old, "n_nonmfc": n, "n_all": current_all[old], "dest": dest})

    payload = {
        "period": "23.01.2026–22.07.2026",
        "total": sum(current_all.values()),
        "non_mfc": nonmfc,
        "mfc": sum(current_all.values()) - nonmfc,
        "current_nonmfc": [{"name": a, "n": b} for a, b in current_nonmfc.most_common()],
        "old_to_new": old_to_new,
        "baskets": {
            "drugoe": {
                "n_all": buckets["Другое"]["n_all"],
                "n_nonmfc": buckets["Другое"]["n_nonmfc"],
                "classified": [
                    {"id": a, "name": ID_NAME[a], "n": b}
                    for a, b in buckets["Другое"]["cls_nonmfc"].most_common()
                ],
                "unrec_nonmfc": buckets["Другое"]["unrec_nonmfc"],
            },
            "dop": {
                "n_all": buckets["Доп"]["n_all"],
                "n_nonmfc": buckets["Доп"]["n_nonmfc"],
                "classified": [
                    {"id": a, "name": ID_NAME[a], "n": b}
                    for a, b in buckets["Доп"]["cls_nonmfc"].most_common()
                ],
                "unrec_nonmfc": buckets["Доп"]["unrec_nonmfc"],
            },
        },
        "to_new_nonmfc": [
            {"id": a, "name": ID_NAME.get(a, a), "n": b} for a, b in to_new.most_common()
        ],
        "estimate": {
            "named_covered_nonmfc": named_cov,
            "basket_classified_nonmfc": basket_cls,
            "basket_unrec_nonmfc": basket_unrec,
            "basket_n_nonmfc": basket_n,
            "empty_nonmfc": empty_nonmfc,
            "coverage_pct_heuristic": round(100 * (named_cov + basket_cls) / nonmfc, 1),
            "nonstandard_low_pct": round(100 * basket_unrec / nonmfc, 1),
            "nonstandard_low_n": basket_unrec,
            "nonstandard_mid_pct": round(100 * (basket_unrec + int(0.25 * empty_nonmfc)) / nonmfc, 1),
            "nonstandard_high_pct": round(100 * (basket_unrec + empty_nonmfc) / nonmfc, 1),
            "note": (
                "Эвристика по заголовкам корзин «Другое»/«Доп.». "
                "KPI Нестандарт — без MFC. Пусто ≠ автоматически Нестандарт."
            ),
        },
        "unrec_sample": [{"title": a, "n": b} for a, b in unrec_titles.most_common(15)],
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(json.dumps(payload["estimate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
