#!/usr/bin/env python3
"""Compare factual bonuses vs proposed normative scoring for the export period."""

from __future__ import annotations

import html as html_lib
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DETAILS_DIR = DATA / "issues"
OUT = ROOT / "analysis"
OUT.mkdir(parents=True, exist_ok=True)

RUB_PER_POINT = 15

# --- New model: typical → base category (T5 / C15 / S30) ---
# Based on docs/01 + nature of work + historical medians (not means — means inflated by outliers).
TYPICAL_BASE: dict[str, tuple[str, int]] = {
    "Не печатаются, не закрываются чеки (сбой ФР, сумма оплат меньше/больше чека)": ("T5", 5),
    "Не закрывается смена": ("T5", 5),
    "Не проходит карта клиента": ("T5", 5),
    "Нет меню, нет товара на кассе": ("T5", 5),
    "Отменить чек (сторнирование или возврат средств)": ("T5", 5),
    "Не работает касса, перезапуск на кассе": ("T5", 5),
    "Не проходит оплата (по банку или процессинг)": ("T5", 5),
    "Не работает ЧЗ": ("T5", 5),  # operational; investigation would be separate typical
    "Не уходят чеки в ОФД": ("T5", 5),
    "Не работает сканер, весы": ("T5", 5),
    "Проблема с оплатой по ДУЭТу": ("T5", 5),
    "Ошибка на кассе (ошибка лицензии, попытка работы задним числом и др)": ("T5", 5),
    "Предоставление доступа": ("T5", 5),
    "Не печатается отчет": ("T5", 5),
    "Не обновились лимиты": ("T5", 5),
    "Вопросы по отчетам": ("C15", 15),
    "Консультация": ("C15", 15),
    "Доп. настройки, сопутствующий сервис, не блокирующий работу": ("C15", 15),
    "Подключение и настройка оборудования": ("S30", 30),
    "Расхождение данных в отчетах с 1С, ОФД и тд.": ("S30", 30),  # investigation track
    "Другое": ("C15", 15),  # until Nonstandard + catalog gaps; not free 500
}

DEFAULT_EMPTY = ("T5", 5)  # empty typical — conservative; MFC bulk often empty
DEFAULT_UNKNOWN = ("C15", 15)

# Investigation-like categories: full S30 weight only for target assignees (docs/15 MVP)
INVESTIGATION_TYPICALS = {
    "Расхождение данных в отчетах с 1С, ОФД и тд.",
}
# Heuristic targets: people with higher share of investigation work historically — placeholder list
# Until management confirms; used only in scenario B2.
INVESTIGATION_TARGETS = {
    "Павлов Андрей Андреевич",
    "Синкин Глеб",
    "Конарев Михаил Михайлович",
}

# Не включать в отчёт/фонд сравнения (шум / нерелевантные строки)
EXCLUDE_ASSIGNEES = {
    "(без ответственного)",
    "Елыков Денис",
    "Меркулов Игорь",
}

# Visit: always +60 when departure (docs/03) — zones not scored
VISIT_POINTS_DEFAULT = 60
X_LONG_POINTS = 15
X_STRONG_POINTS = 30  # сильное осложнение (+30)

# Complication heuristic (scenario upper bound): long work
X_LONG = 15
X_LONG_HOURS = 2.0  # spent_time_total hours threshold (draft)

# MFC: technical bulk tickets are intentionally unscored; daily compensator
# ("МФС. Заявки, звонки") carries the volume. Norm for compensator = T5 × N tech that day.
MFC_TECH_POINTS = 5  # T5 per technical ticket closed that day

# Multi-object pack: one ticket = list of same work on many sites/POS.
# Score should be category_base × N_objects (not a single C15/S30).
BATCH_TITLE_MARKERS = (
    "обновлен",
    "апдейт",
    "update",
    "раскат",
    "спулер",
    "spooler",
    "fshtrih",
    "frontupdater",
    "лого",
    "sdk",
    "установк",
    "запуск",
    "подготовк",
    "фискал",
    "тариф",
    "конфиг",
    "скрипт",
    "все касс",
    "на касс",
)
BATCH_TYPICAL_MARKERS = (
    "доп. настрой",
    "подключение и настройка",
    "другое",
)


def strip_html(html: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.I)
    t = re.sub(r"</(p|tr|li|div)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;", " ", t, flags=re.I)
    return re.sub(r"[ \t]+", " ", t)


def estimate_object_count(title: str, description: str) -> int | None:
    """Best-effort N objects/sites from title/description (tables, codes, 'N касс')."""
    desc = description or ""
    title = title or ""
    text = strip_html(desc) + "\n" + title

    tr = len(re.findall(r"<tr\b", desc, flags=re.I))
    if tr >= 4:
        return tr - 1

    m = re.search(
        r"(\d+)\s*(касс|объект|точк|моноблок|терминал|шт)",
        text,
        flags=re.I,
    )
    if m and int(m.group(1)) >= 2:
        return int(m.group(1))

    codes = {
        c.lower()
        for c in re.findall(
            r"\b(?:vnk|nrk|rnb|evx|gaz|sdx|smt)[\w\-]*\b", text, flags=re.I
        )
    }
    if len(codes) >= 3:
        return len(codes)

    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 5]
    bulletish = [
        ln
        for ln in lines
        if re.match(r"^(\d+[\).]|[-•*])\s+\S", ln) or re.search(r"\bкасс", ln, re.I)
    ]
    if len(bulletish) >= 3:
        return len(bulletish)
    return None


def is_batch_multi_object(
    title: str,
    description: str,
    typical: str | None,
    fact: int | None,
) -> bool:
    """Large score is usually a pack: same typical work × many objects."""
    if not fact or fact < 50:
        return False
    t = (title or "").lower().replace("ё", "е")
    if any(m in t for m in BATCH_TITLE_MARKERS):
        return True
    n = estimate_object_count(title, description)
    if n is not None and n >= 3:
        return True
    typ = (typical or "").lower()
    if fact >= 100 and any(m in typ for m in BATCH_TYPICAL_MARKERS):
        return True
    return False


def batch_pack_score(
    *,
    fact: int,
    typical: str | None,
    watch: bool,
    departure: bool,
    title: str,
    description: str,
) -> tuple[int, str, int]:
    """
    Norm for multi-object pack: unit(category) × N.
    N from description if possible, else inferred from fact/unit (current practice).
    """
    code, base = map_base(typical)
    if departure:
        # Visit replaces typical/N: only fixed visit points (×2 if duty)
        return VISIT_POINTS_DEFAULT * (2 if watch else 1), code, 1
    unit = base * (2 if watch else 1)
    n_text = estimate_object_count(title, description)
    n_from_fact = max(1, int(round(fact / unit))) if unit else 1
    if n_text and n_text >= 2:
        # Prefer text count if it roughly matches the paid magnitude
        if 0.4 * fact <= n_text * unit <= 1.8 * fact:
            n = n_text
        else:
            n = n_from_fact
    else:
        n = n_from_fact
    total = unit * n
    return total, code, n


def is_mfc_compensator(title: str) -> bool:
    """Daily aggregate ticket that pays for MFC tech bulk (not rollouts/installs)."""
    t = (title or "").lower().replace("ё", "е")
    if not re.search(r"(мф[скc]|mfc)", t):
        return False
    # exclude project/rollout work that is also high-scored but not the daily pack
    if any(
        x in t
        for x in (
            "апдейт",
            "лого",
            "спулер",
            "fshtrih",
            "запуск",
            "подготовк",
            "фискал",
            "замен",
            "переезд",
            "терминал",
            "оборудован",
        )
    ):
        return False
    return "заявк" in t


def is_mfc(name: str) -> bool:
    n = name or ""
    u = n.upper().replace("Ё", "Е")
    return "ЭМЭФСИ" in u or "МФС" in n or "MFC" in u


def load_company_names() -> dict[int, str]:
    names: dict[int, str] = {}
    path = DATA / "issues_list.jsonl"
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        company = row.get("company") or {}
        cid, cname = company.get("id"), company.get("name")
        if cid is not None and cname:
            names[int(cid)] = cname
    return names


def param_map(detail: dict) -> dict:
    return {p.get("code"): p.get("value") for p in (detail.get("parameters") or [])}


def to_int_score(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def parse_completed(detail: dict) -> datetime | None:
    for key in ("completed_at", "updated_at"):
        s = detail.get(key)
        if not s:
            continue
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            continue
    return None


def month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def map_base(typical: str | None) -> tuple[str, int]:
    if not typical:
        return DEFAULT_EMPTY
    if typical in TYPICAL_BASE:
        return TYPICAL_BASE[typical]
    return DEFAULT_UNKNOWN


def new_score(
    *,
    typical: str | None,
    watch: bool,
    departure: bool,
    spent_hours: float | None,
    assignee: str,
    apply_complications: bool,
    apply_investigation_gate: bool,
    score_untyped_as_empty: bool = True,
) -> tuple[int, str]:
    """Return (points, category_code)."""
    code, base = map_base(typical)

    # Investigation gate: non-target gets conveyor weight (T5) instead of S30
    if (
        apply_investigation_gate
        and typical in INVESTIGATION_TYPICALS
        and assignee not in INVESTIGATION_TARGETS
    ):
        code, base = "T5", 5

    if departure:
        # Visit-only scoring: ignore typical base, complications, N
        total = VISIT_POINTS_DEFAULT * (2 if watch else 1)
        return total, code

    extra = 0
    if apply_complications and spent_hours is not None and spent_hours >= X_LONG_HOURS:
        extra += X_LONG
        # soft cap of +30 total complications — here only X_LONG
        extra = min(extra, 30)

    total = base + extra
    if watch:
        total *= 2
    return total, code


def load_details() -> list[dict]:
    rows = []
    for path in sorted(DETAILS_DIR.glob("*.json")):
        if path.name.startswith("._"):
            continue
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def fmt_rub(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def fmt_delta(n: float) -> str:
    sign = "+" if n > 0 else ""
    return f"{sign}{fmt_rub(n)}"


def pct(new: float, old: float) -> str:
    if old == 0:
        return "n/a"
    return f"{(new / old - 1) * 100:+.1f}%"


def pct_num(new: float, old: float) -> float | None:
    if old == 0:
        return None
    return (new / old - 1) * 100


MONTH_RU = {
    "01": "янв",
    "02": "фев",
    "03": "мар",
    "04": "апр",
    "05": "май",
    "06": "июн",
    "07": "июл",
    "08": "авг",
    "09": "сен",
    "10": "окт",
    "11": "ноя",
    "12": "дек",
}


def month_label(mk: str) -> str:
    y, m = mk.split("-")
    return f"{MONTH_RU.get(m, m)} {y}"


def slugify(name: str) -> str:
    return (
        name.replace(" ", "-")
        .replace("(", "")
        .replace(")", "")
        .replace("«", "")
        .replace("»", "")
        .replace(",", "")
        .replace(".", "")
    )


def delta_class(delta: float) -> str:
    if abs(delta) < 1:
        return "flat"
    return "up" if delta > 0 else "down"


DRIVER_META = {
    "batch_pack": {
        "title": "Пакет по объектам (N × норма)",
        "why": "Крупная заявка — обычно перечень однотипных работ по объектам/кассам. Норма = база категории × N (N из описания или восстановлено из факта), без срезания до «одной штуки».",
    },
    "high_tail": {
        "title": "Срез крупного балла без признаков пакета",
        "why": "Балл ≥100, но нет маркеров массовой раскатки/перечня объектов — начисляется одна норма категории, не свободная цифра.",
    },
    "mfc_day": {
        "title": "Дневной компенсатор MFC",
        "why": "Пакет «МФС. Заявки, звонки» пересчитывается как T5 × число техзаявок за день вместо произвольного крупного балла.",
    },
    "norm_up": {
        "title": "Рост по нормам каталога",
        "why": "Часть заявок с фактом 5–10 поднимается: консультации/доп.настройки → C15=15, сложные/расхождения/оборудование → S30=30; в дежурство ещё ×2.",
    },
    "norm_down": {
        "title": "Снижение средних самооценок",
        "why": "Заявки с фактом 20–90 на типовых (не пакет) садятся на норму T5/C15.",
    },
}


def classify_scored_driver(
    *,
    compensator: bool,
    batch: bool,
    fact: int,
    new_pts: int,
) -> str:
    if compensator:
        return "mfc_day"
    if batch:
        return "batch_pack"
    if fact >= 100:
        return "high_tail"
    if new_pts > fact:
        return "norm_up"
    if new_pts < fact:
        return "norm_down"
    return "flat"


def build_explanation_text(name: str, drv: dict, rub: int) -> dict:
    """Build structured explanation for one assignee."""
    fact_pts = drv.get("fact_pts", 0.0)
    new_pts = drv.get("new_pts", 0.0)
    delta_pts = new_pts - fact_pts
    fact_rub = fact_pts * rub
    new_rub = new_pts * rub
    delta_rub = delta_pts * rub

    parts: list[dict] = []
    for key in ("batch_pack", "high_tail", "mfc_day", "norm_up", "norm_down"):
        block = drv.get(key) or {}
        pts = float(block.get("pts", 0))
        n = int(block.get("n", 0))
        if n == 0 and abs(pts) < 0.5:
            continue
        meta = DRIVER_META[key]
        examples = block.get("examples") or []
        ex_txt = []
        for ex in examples[:3]:
            ex_txt.append(
                f"«{ex['title']}»: {ex['fact']}→{ex['new']} б."
                + (f" ({ex['typical']})" if ex.get("typical") else "")
            )
        parts.append(
            {
                "key": key,
                "title": meta["title"],
                "why": meta["why"],
                "n": n,
                "delta_pts": pts,
                "delta_rub": pts * rub,
                "examples": ex_txt,
            }
        )

    parts.sort(key=lambda p: -abs(p["delta_rub"]))

    # Lead sentence
    if abs(delta_rub) < 500:
        lead = (
            f"Scored почти не меняется ({fmt_rub(fact_rub)} → {fmt_rub(new_rub)} ₽): "
            f"плюсы и минусы норм взаимно гасятся."
        )
    elif delta_rub < 0:
        lead = (
            f"Scored снижается на {fmt_rub(abs(delta_rub))} ₽ "
            f"({fmt_rub(fact_rub)} → {fmt_rub(new_rub)}, {pct(new_rub, fact_rub)})."
        )
    else:
        lead = (
            f"Scored растёт на {fmt_rub(delta_rub)} ₽ "
            f"({fmt_rub(fact_rub)} → {fmt_rub(new_rub)}, {pct(new_rub, fact_rub)})."
        )

    # Dominant cause — in the direction of the net change
    if not parts:
        dominant = "Существенных сдвигов по отдельным драйверам нет."
    elif abs(delta_rub) < 500:
        neg = [p for p in parts if p["delta_rub"] < 0]
        pos = [p for p in parts if p["delta_rub"] > 0]
        bits = []
        if neg:
            t = max(neg, key=lambda p: abs(p["delta_rub"]))
            bits.append(f"минус {t['title'].lower()} ({fmt_delta(t['delta_rub'])} ₽)")
        if pos:
            t = max(pos, key=lambda p: abs(p["delta_rub"]))
            bits.append(f"плюс {t['title'].lower()} ({fmt_delta(t['delta_rub'])} ₽)")
        dominant = "Баланс: " + ", ".join(bits) + "." if bits else "Изменения взаимно гасятся."
    elif delta_rub < 0:
        neg = [p for p in parts if p["delta_rub"] < 0]
        top = max(neg, key=lambda p: abs(p["delta_rub"])) if neg else parts[0]
        dominant = f"Главный фактор снижения: {top['title'].lower()} ({fmt_delta(top['delta_rub'])} ₽)."
        pos = [p for p in parts if p["delta_rub"] > 0]
        if pos:
            up = max(pos, key=lambda p: abs(p["delta_rub"]))
            if abs(up["delta_rub"]) >= 10000:
                dominant += (
                    f" Частично компенсируется: {up['title'].lower()} "
                    f"({fmt_delta(up['delta_rub'])} ₽)."
                )
    else:
        pos = [p for p in parts if p["delta_rub"] > 0]
        top = max(pos, key=lambda p: abs(p["delta_rub"])) if pos else parts[0]
        dominant = f"Главный фактор роста: {top['title'].lower()} ({fmt_delta(top['delta_rub'])} ₽)."
        neg = [p for p in parts if p["delta_rub"] < 0]
        if neg:
            dn = max(neg, key=lambda p: abs(p["delta_rub"]))
            if abs(dn["delta_rub"]) >= 10000:
                dominant += (
                    f" Сдерживается: {dn['title'].lower()} ({fmt_delta(dn['delta_rub'])} ₽)."
                )

    return {
        "lead": lead,
        "dominant": dominant,
        "parts": parts,
        "fact_rub": fact_rub,
        "new_rub": new_rub,
        "delta_rub": delta_rub,
    }


def render_bonus_html(
    *,
    meta: dict,
    months: list[str],
    main_assignees: list[str],
    by_a: dict,
    by_am: dict,
    by_m: dict,
    totals: dict,
    rub: int,
    explanations: dict[str, dict] | None = None,
) -> str:
    """Standalone HTML: per-engineer monthly fact vs new approach."""
    esc = html_lib.escape
    fact_rub = totals["fact"]["points"] * rub
    new_sc_rub = totals["new_scored_only"]["points"] * rub
    new_all_rub = totals["new_all"]["points"] * rub
    d_sc = new_sc_rub - fact_rub
    d_all = new_all_rub - fact_rub

    fact_reg = totals["fact"]["points_reg"] * rub
    fact_duty = totals["fact"]["points_duty"] * rub
    new_sc_reg = totals["new_scored_only"]["points_reg"] * rub
    new_sc_duty = totals["new_scored_only"]["points_duty"] * rub
    new_all_reg = totals["new_all"]["points_reg"] * rub
    new_all_duty = totals["new_all"]["points_duty"] * rub

    explanations = explanations or {}

    overview_rows = []
    for a in main_assignees:
        fa = by_a["fact"][a]
        ns = by_a["new_scored_only"][a]
        na = by_a["new_all"][a]
        overview_rows.append(
            {
                "name": a,
                "slug": slugify(a),
                "tickets": int(fa["tickets"]),
                "scored": int(fa["scored_tickets"]),
                "tickets_reg": int(fa["tickets_reg"]),
                "tickets_duty": int(fa["tickets_duty"]),
                "fact": fa["points"] * rub,
                "fact_reg": fa["points_reg"] * rub,
                "fact_duty": fa["points_duty"] * rub,
                "new_sc": ns["points"] * rub,
                "new_sc_reg": ns["points_reg"] * rub,
                "new_sc_duty": ns["points_duty"] * rub,
                "new_all": na["points"] * rub,
                "new_all_reg": na["points_reg"] * rub,
                "new_all_duty": na["points_duty"] * rub,
                "delta_sc": ns["points"] * rub - fa["points"] * rub,
                "delta_sc_reg": ns["points_reg"] * rub - fa["points_reg"] * rub,
                "delta_sc_duty": ns["points_duty"] * rub - fa["points_duty"] * rub,
                "delta_all": na["points"] * rub - fa["points"] * rub,
                "pct_sc": pct_num(ns["points"] * rub, fa["points"] * rub),
                "explain": explanations.get(a),
            }
        )

    parts: list[str] = []
    parts.append(
        f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Сравнение премий по инженерам — факт vs новый подход</title>
  <style>
    :root {{
      --bg: #f4f5f7; --surface: #fff; --text: #1a1d23; --muted: #5c6570; --faint: #8b939e;
      --line: #e2e5ea; --accent: #1f4b7a; --warn-bg: #fff6e8; --warn-border: #e6b35c;
      --info-bg: #eef5fb; --info-border: #7aa7d0; --ok-bg: #eef8f1; --down: #b42318; --up: #1f6b3a;
      --bar-fact: #5c6570; --bar-new: #1f4b7a; --bar-all: #3d7ab0;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); line-height: 1.45; }}
    .wrap {{ max-width: 1120px; margin: 0 auto; padding: 28px 20px 80px; }}
    h1 {{ font-size: 1.55rem; font-weight: 700; margin: 0 0 8px; letter-spacing: -0.02em; }}
    .lead {{ color: var(--muted); margin: 0 0 16px; max-width: 80ch; }}
    .caption {{ color: var(--faint); font-size: 0.78rem; }}
    .banner {{
      background: #1f4b7a; color: #fff; border-radius: 12px; padding: 16px 18px; margin-bottom: 18px;
    }}
    .banner a {{ color: #cfe3ff; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
    @media (max-width: 900px) {{ .stats {{ grid-template-columns: repeat(2, 1fr); }} }}
    .stat {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }}
    .stat .v {{ font-size: 1.25rem; font-weight: 700; color: var(--accent); }}
    .stat .v.down {{ color: var(--down); }}
    .stat .v.up {{ color: var(--up); }}
    .stat .l {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; }}
    .stat .sub {{ font-size: 0.78rem; color: var(--muted); margin-top: 6px; line-height: 1.35; }}
    .legend-box {{
      background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
      padding: 14px 16px; margin: 0 0 16px; font-size: 0.88rem;
    }}
    .legend-box h2 {{ font-size: 0.95rem; margin: 0 0 8px; }}
    .legend-box ul {{ margin: 0; padding-left: 18px; }}
    .legend-box li {{ margin: 4px 0; color: var(--muted); }}
    .legend-box li b {{ color: var(--text); }}
    .legend-box code {{ font-size: 0.88em; background: #eef1f4; padding: 1px 5px; border-radius: 4px; }}
    .split-tag {{
      display: inline-block; font-size: 0.68rem; font-weight: 700; padding: 1px 6px; border-radius: 4px;
      margin-right: 4px; vertical-align: middle;
    }}
    .split-tag.reg {{ background: #eef2f6; color: #3d4654; }}
    .split-tag.duty {{ background: #fff6e8; color: #8a5a00; }}
    .callout {{ border-radius: 10px; padding: 12px 14px; margin: 12px 0 18px; border: 1px solid var(--info-border); background: var(--info-bg); font-size: 0.9rem; }}
    .nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 20px; }}
    .nav a {{
      font-size: 0.8rem; color: var(--accent); text-decoration: none; border: 1px solid var(--line);
      background: var(--surface); padding: 6px 10px; border-radius: 8px;
    }}
    .nav a:hover {{ border-color: var(--accent); }}
    .card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 12px; margin: 18px 0; overflow: hidden; }}
    .card-h {{
      padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; flex-wrap: wrap;
      justify-content: space-between; gap: 10px; align-items: flex-start;
    }}
    .card-h .name {{ font-weight: 700; font-size: 1.05rem; }}
    .card-h .meta {{ font-size: 0.82rem; color: var(--muted); }}
    .pills {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .pill {{
      display: inline-block; font-size: 0.72rem; font-weight: 650; padding: 3px 9px; border-radius: 999px;
      background: #eef2f6; color: var(--muted);
    }}
    .pill.down {{ background: #fdecea; color: var(--down); }}
    .pill.up {{ background: var(--ok-bg); color: var(--up); }}
    .pill.flat {{ background: #eef2f6; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ padding: 8px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }}
    th {{
      font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted);
      font-weight: 600; background: #fafbfc;
    }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    tr.total td {{ font-weight: 650; background: #f7f8fa; border-bottom: 0; }}
    tr:last-child td {{ border-bottom: 0; }}
    .delta.down {{ color: var(--down); font-weight: 650; }}
    .delta.up {{ color: var(--up); font-weight: 650; }}
    .delta.flat {{ color: var(--muted); }}
    .bars {{ display: flex; flex-direction: column; gap: 4px; min-width: 120px; }}
    .bar-row {{ display: grid; grid-template-columns: 42px 1fr; gap: 6px; align-items: center; font-size: 0.68rem; color: var(--muted); }}
    .bar-track {{ height: 8px; background: #eef1f4; border-radius: 4px; overflow: hidden; }}
    .bar-fill {{ height: 100%; border-radius: 4px; }}
    .bar-fill.fact {{ background: var(--bar-fact); }}
    .bar-fill.new {{ background: var(--bar-new); }}
    .bar-fill.all {{ background: var(--bar-all); }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.8rem; color: var(--muted); margin: 8px 0 0; }}
    .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: middle; }}
    .legend .f {{ background: var(--bar-fact); }}
    .legend .n {{ background: var(--bar-new); }}
    .legend .a {{ background: var(--bar-all); }}
    footer {{ margin-top: 40px; color: var(--faint); font-size: 0.8rem; border-top: 1px solid var(--line); padding-top: 16px; }}
    code {{ font-size: 0.88em; background: #eef1f4; padding: 1px 5px; border-radius: 4px; }}
    .top-link {{ float: right; font-size: 0.78rem; font-weight: 500; color: var(--accent); text-decoration: none; }}
    .explain {{
      margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line);
      background: #f7f9fc; font-size: 0.88rem;
    }}
    .explain .lead {{ color: var(--text); margin: 0 0 6px; font-weight: 650; max-width: none; }}
    .explain .dom {{ color: var(--muted); margin: 0 0 10px; }}
    .explain ul {{ margin: 0; padding-left: 18px; }}
    .explain li {{ margin: 6px 0; }}
    .explain .why {{ color: var(--muted); font-size: 0.82rem; }}
    .explain .ex {{ color: var(--faint); font-size: 0.78rem; margin-top: 2px; }}
    .explain .amt.down {{ color: var(--down); font-weight: 650; }}
    .explain .amt.up {{ color: var(--up); font-weight: 650; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="banner" id="top">
      <strong style="display:block;margin-bottom:6px">Премии по инженерам: текущий подход vs новый</strong>
      Период: {esc(str(meta.get('since', '?')))} — {esc(str(meta.get('until', '?')))}
      · заявок в выборке: <b>{meta.get('list_count', '—')}</b>
      · подробный текст: <a href="bonus-comparison.md">bonus-comparison.md</a>
    </div>

    <div class="legend-box">
      <h2>Легенда расчёта</h2>
      <ul>
        <li><b>1 балл = {rub} ₽</b>. Премия (₽) = сумма баллов × {rub}.</li>
        <li><b>Две статьи расходов</b> по чекбоксу <code>watch</code> (Дежурство):
          <span class="split-tag reg">обычные</span> заявки без дежурства и
          <span class="split-tag duty">дежурство</span> заявки с дежурством — считаются и сравниваются отдельно.</li>
        <li><b>Текущий</b> — поле <code>ticket_weight</code> как проставил инженер (нет баллов → 0 ₽).</li>
        <li><b>Новый (scored)</b> — нормативный каталог только там, где баллы уже стояли.</li>
        <li><b>Новый (все)</b> — нормы на заявки с работой; MFC-техbulk без баллов = 0; компенсатор MFC = T5×N за день.</li>
        <li><b>Формула нормы</b>: без выезда <code>(база × N + осложнение)</code>; с выездом <code>только 60</code>; в дежурстве ещё <code>×2</code>.</li>
        <li>Базы: <b>T5=5</b>, <b>C15=15</b>, <b>S30=30</b>; выезд = <b>только +60</b> (без суммы с typical); осложнение +15/+30 только без выезда.</li>
      </ul>
    </div>

    <h1>Сравнение по сотрудникам и месяцам</h1>

    <div class="stats">
      <div class="stat">
        <div class="v">{esc(fmt_rub(fact_rub))} ₽</div>
        <div class="l">Факт всего</div>
        <div class="sub"><span class="split-tag reg">обыч.</span>{esc(fmt_rub(fact_reg))} ₽<br>
          <span class="split-tag duty">деж.</span>{esc(fmt_rub(fact_duty))} ₽</div>
      </div>
      <div class="stat">
        <div class="v {delta_class(d_sc)}">{esc(fmt_rub(new_sc_rub))} ₽</div>
        <div class="l">Новый scored · {esc(pct(new_sc_rub, fact_rub))}</div>
        <div class="sub"><span class="split-tag reg">обыч.</span>{esc(fmt_rub(new_sc_reg))} ₽ ({esc(pct(new_sc_reg, fact_reg))})<br>
          <span class="split-tag duty">деж.</span>{esc(fmt_rub(new_sc_duty))} ₽ ({esc(pct(new_sc_duty, fact_duty))})</div>
      </div>
      <div class="stat">
        <div class="v {delta_class(d_all)}">{esc(fmt_rub(new_all_rub))} ₽</div>
        <div class="l">Новый все · {esc(pct(new_all_rub, fact_rub))}</div>
        <div class="sub"><span class="split-tag reg">обыч.</span>{esc(fmt_rub(new_all_reg))} ₽<br>
          <span class="split-tag duty">деж.</span>{esc(fmt_rub(new_all_duty))} ₽</div>
      </div>
      <div class="stat"><div class="v">{len(main_assignees)}</div><div class="l">Инженеров в отчёте</div></div>
    </div>

    <div class="callout">
      У каждого сотрудника две статьи премии: <b>обычные заявки</b> и <b>дежурство</b> (отдельный контур расходов).
      Δ красный = ниже факта, зелёный = выше. MFC-техbulk без баллов = 0 (оплата через дневной компенсатор).
      Пакетные заявки (раскатка по объектам) = норма × N.
    </div>

    <div class="legend">
      <span><i class="f"></i>Текущий</span>
      <span><i class="n"></i>Новый (scored)</span>
      <span><i class="a"></i>Новый (все)</span>
    </div>
"""
    )

    parts.append(
        '<div class="card"><div class="card-h"><div class="name">Сводка по инженерам '
        '(обычные / дежурство / итого)</div></div>'
    )
    parts.append(
        """<table>
      <thead>
        <tr>
          <th>Инженер</th>
          <th class="num">Заявок<br><span class="caption">обыч./деж.</span></th>
          <th class="num">Факт обыч., ₽</th>
          <th class="num">Новый scored обыч., ₽</th>
          <th class="num">Δ обыч.</th>
          <th class="num">Факт деж., ₽</th>
          <th class="num">Новый scored деж., ₽</th>
          <th class="num">Δ деж.</th>
          <th class="num">Итого Δ scored</th>
        </tr>
      </thead>
      <tbody>"""
    )
    for row in overview_rows:
        parts.append(
            f"""<tr>
          <td><a href="#{esc(row['slug'])}">{esc(row['name'])}</a></td>
          <td class="num">{row['tickets_reg']} / {row['tickets_duty']}</td>
          <td class="num">{esc(fmt_rub(row['fact_reg']))}</td>
          <td class="num">{esc(fmt_rub(row['new_sc_reg']))}</td>
          <td class="num delta {delta_class(row['delta_sc_reg'])}">{esc(fmt_delta(row['delta_sc_reg']))}</td>
          <td class="num">{esc(fmt_rub(row['fact_duty']))}</td>
          <td class="num">{esc(fmt_rub(row['new_sc_duty']))}</td>
          <td class="num delta {delta_class(row['delta_sc_duty'])}">{esc(fmt_delta(row['delta_sc_duty']))}</td>
          <td class="num delta {delta_class(row['delta_sc'])}">{esc(fmt_delta(row['delta_sc']))}</td>
        </tr>"""
        )
    parts.append(
        f"""<tr class="total">
          <td>Итого</td>
          <td class="num">{int(totals['fact']['tickets_reg'])} / {int(totals['fact']['tickets_duty'])}</td>
          <td class="num">{esc(fmt_rub(fact_reg))}</td>
          <td class="num">{esc(fmt_rub(new_sc_reg))}</td>
          <td class="num delta {delta_class(new_sc_reg - fact_reg)}">{esc(fmt_delta(new_sc_reg - fact_reg))}</td>
          <td class="num">{esc(fmt_rub(fact_duty))}</td>
          <td class="num">{esc(fmt_rub(new_sc_duty))}</td>
          <td class="num delta {delta_class(new_sc_duty - fact_duty)}">{esc(fmt_delta(new_sc_duty - fact_duty))}</td>
          <td class="num delta {delta_class(d_sc)}">{esc(fmt_delta(d_sc))}</td>
        </tr>"""
    )
    parts.append("</tbody></table></div>")

    parts.append('<nav class="nav">')
    for row in overview_rows:
        short = row["name"].split()[0]
        parts.append(f'<a href="#{esc(row["slug"])}">{esc(short)}</a>')
    parts.append("</nav>")

    parts.append(
        """<div class="card" id="company-months">
      <div class="card-h"><div class="name">Вся команда по месяцам (обычные / дежурство)</div></div>
      <table>
        <thead>
          <tr>
            <th>Месяц</th>
            <th class="num">Заявок<br><span class="caption">обыч./деж.</span></th>
            <th class="num">Факт обыч.</th>
            <th class="num">Новый обыч.</th>
            <th class="num">Δ обыч.</th>
            <th class="num">Факт деж.</th>
            <th class="num">Новый деж.</th>
            <th class="num">Δ деж.</th>
            <th class="num">Итого Δ scored</th>
          </tr>
        </thead>
        <tbody>"""
    )
    for mk in months:
        fm = by_m["fact"][mk]
        nsm = by_m["new_scored_only"][mk]
        fr = fm["points_reg"] * rub
        fd = fm["points_duty"] * rub
        nsr = nsm["points_reg"] * rub
        nsd = nsm["points_duty"] * rub
        dlt_r = nsr - fr
        dlt_d = nsd - fd
        dlt = (nsr + nsd) - (fr + fd)
        parts.append(
            f"""<tr>
          <td>{esc(month_label(mk))}</td>
          <td class="num">{int(fm['tickets_reg'])} / {int(fm['tickets_duty'])}</td>
          <td class="num">{esc(fmt_rub(fr))}</td>
          <td class="num">{esc(fmt_rub(nsr))}</td>
          <td class="num delta {delta_class(dlt_r)}">{esc(fmt_delta(dlt_r))}</td>
          <td class="num">{esc(fmt_rub(fd))}</td>
          <td class="num">{esc(fmt_rub(nsd))}</td>
          <td class="num delta {delta_class(dlt_d)}">{esc(fmt_delta(dlt_d))}</td>
          <td class="num delta {delta_class(dlt)}">{esc(fmt_delta(dlt))}</td>
        </tr>"""
        )
    parts.append(
        f"""<tr class="total">
          <td>Итого</td>
          <td class="num">{int(totals['fact']['tickets_reg'])} / {int(totals['fact']['tickets_duty'])}</td>
          <td class="num">{esc(fmt_rub(fact_reg))}</td>
          <td class="num">{esc(fmt_rub(new_sc_reg))}</td>
          <td class="num delta {delta_class(new_sc_reg - fact_reg)}">{esc(fmt_delta(new_sc_reg - fact_reg))}</td>
          <td class="num">{esc(fmt_rub(fact_duty))}</td>
          <td class="num">{esc(fmt_rub(new_sc_duty))}</td>
          <td class="num delta {delta_class(new_sc_duty - fact_duty)}">{esc(fmt_delta(new_sc_duty - fact_duty))}</td>
          <td class="num delta {delta_class(d_sc)}">{esc(fmt_delta(d_sc))}</td>
        </tr>"""
    )
    parts.append("</tbody></table></div>")

    for row in overview_rows:
        a = row["name"]
        slug = row["slug"]
        dc = delta_class(row["delta_sc"])

        month_vals = []
        for mk in months:
            key = (a, mk)
            fm = by_am["fact"][key]
            nsm = by_am["new_scored_only"][key]
            t = int(fm["tickets"] or by_am["new_all"][key]["tickets"])
            fr = fm["points_reg"] * rub
            fd = fm["points_duty"] * rub
            nsr = nsm["points_reg"] * rub
            nsd = nsm["points_duty"] * rub
            if t == 0 and fr == 0 and fd == 0 and nsr == 0 and nsd == 0:
                continue
            month_vals.append(
                (
                    mk,
                    int(fm["tickets_reg"]),
                    int(fm["tickets_duty"]),
                    fr,
                    nsr,
                    fd,
                    nsd,
                )
            )

        parts.append(
            f"""<div class="card" id="{esc(slug)}">
      <div class="card-h">
        <div>
          <div class="name">{esc(a)} <a class="top-link" href="#top">↑ к сводке</a></div>
          <div class="meta">заявок: {row['tickets_reg']} обыч. / {row['tickets_duty']} деж. · с баллами: {row['scored']}</div>
        </div>
        <div class="pills">
          <span class="pill"><span class="split-tag reg">обыч.</span>{esc(fmt_rub(row['fact_reg']))} → {esc(fmt_rub(row['new_sc_reg']))} ₽
            <span class="delta {delta_class(row['delta_sc_reg'])}">{esc(fmt_delta(row['delta_sc_reg']))}</span></span>
          <span class="pill"><span class="split-tag duty">деж.</span>{esc(fmt_rub(row['fact_duty']))} → {esc(fmt_rub(row['new_sc_duty']))} ₽
            <span class="delta {delta_class(row['delta_sc_duty'])}">{esc(fmt_delta(row['delta_sc_duty']))}</span></span>
          <span class="pill {dc}">итого scored {esc(fmt_delta(row['delta_sc']))}</span>
        </div>
      </div>
"""
        )
        expl = row.get("explain")
        if expl:
            parts.append('<div class="explain">')
            parts.append(f'<p class="lead">{esc(expl["lead"])}</p>')
            parts.append(f'<p class="dom">{esc(expl["dominant"])}</p>')
            if expl.get("parts"):
                parts.append("<ul>")
                for p in expl["parts"]:
                    amt_cls = delta_class(p["delta_rub"])
                    parts.append("<li>")
                    parts.append(
                        f'<span class="amt {amt_cls}">{esc(fmt_delta(p["delta_rub"]))} ₽</span> '
                        f'· <b>{esc(p["title"])}</b> ({p["n"]} заяв.)'
                    )
                    parts.append(f'<div class="why">{esc(p["why"])}</div>')
                    if p.get("examples"):
                        parts.append(
                            f'<div class="ex">Примеры: {esc("; ".join(p["examples"]))}</div>'
                        )
                    parts.append("</li>")
                parts.append("</ul>")
            parts.append("</div>")

        parts.append(
            """      <table>
        <thead>
          <tr>
            <th>Месяц</th>
            <th class="num">Заявок<br><span class="caption">обыч./деж.</span></th>
            <th class="num">Факт обыч., ₽</th>
            <th class="num">Новый обыч., ₽</th>
            <th class="num">Δ обыч.</th>
            <th class="num">Факт деж., ₽</th>
            <th class="num">Новый деж., ₽</th>
            <th class="num">Δ деж.</th>
          </tr>
        </thead>
        <tbody>"""
        )

        for mk, tr, td, fr, nsr, fd, nsd in month_vals:
            dlt_r = nsr - fr
            dlt_d = nsd - fd
            parts.append(
                f"""<tr>
          <td>{esc(month_label(mk))}</td>
          <td class="num">{tr} / {td}</td>
          <td class="num">{esc(fmt_rub(fr))}</td>
          <td class="num">{esc(fmt_rub(nsr))}</td>
          <td class="num delta {delta_class(dlt_r)}">{esc(fmt_delta(dlt_r))}</td>
          <td class="num">{esc(fmt_rub(fd))}</td>
          <td class="num">{esc(fmt_rub(nsd))}</td>
          <td class="num delta {delta_class(dlt_d)}">{esc(fmt_delta(dlt_d))}</td>
        </tr>"""
            )

        parts.append(
            f"""<tr class="total">
          <td>Итого</td>
          <td class="num">{row['tickets_reg']} / {row['tickets_duty']}</td>
          <td class="num">{esc(fmt_rub(row['fact_reg']))}</td>
          <td class="num">{esc(fmt_rub(row['new_sc_reg']))}</td>
          <td class="num delta {delta_class(row['delta_sc_reg'])}">{esc(fmt_delta(row['delta_sc_reg']))}</td>
          <td class="num">{esc(fmt_rub(row['fact_duty']))}</td>
          <td class="num">{esc(fmt_rub(row['new_sc_duty']))}</td>
          <td class="num delta {delta_class(row['delta_sc_duty'])}">{esc(fmt_delta(row['delta_sc_duty']))}</td>
        </tr>"""
        )
        parts.append("</tbody></table></div>")

    parts.append(
        f"""<footer>
      Сгенерировано {esc(datetime.now().strftime('%Y-%m-%d %H:%M'))} ·
      <code>python scripts/compare_bonus_models.py</code> ·
      1 балл = {rub} ₽ · модель: docs/00–04, 11, 15
    </footer>
  </div>
</body>
</html>"""
    )
    return "\n".join(parts)


def main() -> None:
    company_names = load_company_names()
    details = load_details()
    if not details:
        raise SystemExit("No data/issues — run fetch first")

    # Accumulators: fact / new_base / new_strict_scored_only / new_with_X / new_with_gate
    # Keys: (assignee, month) and totals
    modes = (
        "fact",  # ticket_weight as entered; no score → 0; watch NOT re-multiplied
        "fact_duty_x2",  # if watch: treat entered score as base and ×2 (upper estimate of current if ×2 applied at payout)
        "new_all",  # normative on ALL tickets incl. previously unscored
        "new_scored_only",  # normative only where fact had a score (apples-to-apples volume)
        "new_no_mfc",  # normative on all non-MFC; MFC = 0 (or keep fact? use 0 for "segment out")
        "new_all_xlong",  # new_all + X_LONG heuristic
        "new_all_gate",  # new_all + investigation gate
    )

    def empty_bucket() -> dict[str, float]:
        return {
            "points": 0.0,
            "tickets": 0,
            "scored_tickets": 0,
            "points_reg": 0.0,
            "points_duty": 0.0,
            "tickets_reg": 0,
            "tickets_duty": 0,
            "scored_reg": 0,
            "scored_duty": 0,
        }

    by_am: dict[str, dict[tuple[str, str], dict[str, float]]] = {
        m: defaultdict(empty_bucket) for m in modes
    }
    by_a: dict[str, dict[str, dict[str, float]]] = {
        m: defaultdict(empty_bucket) for m in modes
    }
    by_m: dict[str, dict[str, dict[str, float]]] = {
        m: defaultdict(empty_bucket) for m in modes
    }
    totals: dict[str, dict[str, float]] = {m: empty_bucket() for m in modes}

    # Diagnostics
    cat_counter = Counter()
    fact_hist = Counter()
    high_cut = []  # fact >= 100 replaced in new
    mfc_unscored = 0
    non_mfc_unscored = 0
    skipped_no_month = 0
    mfc_comp_n = 0
    mfc_comp_fact_pts = 0
    mfc_comp_new_pts = 0
    mfc_bulk_zeroed = 0

    # Per-assignee scored delta drivers (only tickets with fact score)
    scored_drv: dict[str, dict] = defaultdict(
        lambda: {
            "fact_pts": 0.0,
            "new_pts": 0.0,
            "high_tail": {"pts": 0.0, "n": 0, "examples": []},
            "batch_pack": {"pts": 0.0, "n": 0, "examples": []},
            "mfc_day": {"pts": 0.0, "n": 0, "examples": []},
            "norm_up": {"pts": 0.0, "n": 0, "examples": []},
            "norm_down": {"pts": 0.0, "n": 0, "examples": []},
            "flat": {"pts": 0.0, "n": 0, "examples": []},
        }
    )

    # Pass 1: enrich + count MFC technical (unscored, non-compensator) per calendar day
    records: list[dict] = []
    mfc_tech_by_day: Counter = Counter()

    for d in details:
        pm = param_map(d)
        assignee = (d.get("assignee") or {}).get("name") or "(без ответственного)"
        dt = parse_completed(d)
        if not dt:
            skipped_no_month += 1
            continue
        mk = month_key(dt)
        day = dt.strftime("%Y-%m-%d")
        cid = d.get("company_id")
        cname = company_names.get(int(cid), "") if cid is not None else ""
        mfc = is_mfc(cname)
        title = d.get("title") or ""
        description = d.get("description") or ""
        typical = pm.get("typical")
        if isinstance(typical, list):
            typical = typical[0] if typical else None
        watch = bool(pm.get("watch"))
        departure = bool(pm.get("departure"))
        spent = d.get("spent_time_total")
        try:
            spent_h = float(spent) if spent is not None else None
        except (TypeError, ValueError):
            spent_h = None

        fact = to_int_score(pm.get("ticket_weight"))
        has_score = fact is not None
        compensator = mfc and is_mfc_compensator(title)
        # Technical bulk: MFC, not the daily pack, intentionally without scores
        mfc_bulk = mfc and (not compensator) and (not has_score)
        batch = (not compensator) and is_batch_multi_object(
            title, description, typical, fact
        )

        if mfc_bulk:
            mfc_tech_by_day[day] += 1

        records.append(
            {
                "id": d.get("id"),
                "assignee": assignee,
                "mk": mk,
                "day": day,
                "mfc": mfc,
                "title": title,
                "description": description,
                "typical": typical,
                "watch": watch,
                "departure": departure,
                "spent_h": spent_h,
                "fact": fact,
                "has_score": has_score,
                "compensator": compensator,
                "mfc_bulk": mfc_bulk,
                "batch": batch,
            }
        )

    # Pass 2: score
    excluded_tickets = 0
    for rec in records:
        assignee = rec["assignee"]
        if assignee in EXCLUDE_ASSIGNEES:
            excluded_tickets += 1
            continue
        mk = rec["mk"]
        day = rec["day"]
        mfc = rec["mfc"]
        typical = rec["typical"]
        watch = rec["watch"]
        departure = rec["departure"]
        spent_h = rec["spent_h"]
        fact = rec["fact"]
        has_score = rec["has_score"]
        compensator = rec["compensator"]
        mfc_bulk = rec["mfc_bulk"]
        batch = rec["batch"]
        title = rec["title"]
        description = rec["description"]

        fact_pts = float(fact or 0)
        if has_score:
            fact_hist[fact] += 1
            if fact >= 100 and not batch:
                high_cut.append((rec["id"], assignee, fact, typical, mk))

        fact_x2 = float(fact or 0) * (2 if watch and has_score else 1)

        if mfc_bulk:
            # Intentionally unscored tech tickets — paid via daily compensator
            n_all, cat = 0, "MFC_BULK"
            mfc_bulk_zeroed += 1
            mfc_unscored += 1
        elif compensator:
            if departure:
                n_all = VISIT_POINTS_DEFAULT * (2 if watch else 1)
            else:
                tech_n = mfc_tech_by_day.get(day, 0)
                base = MFC_TECH_POINTS * tech_n
                if base <= 0:
                    # rare day without unscored tech — keep a small floor, not free 500
                    base = MFC_TECH_POINTS
                n_all = base * (2 if watch else 1)
            cat = "MFC_DAY"
            mfc_comp_n += 1
            mfc_comp_fact_pts += int(fact or 0)
            mfc_comp_new_pts += n_all
        elif batch and has_score:
            n_all, code, n_obj = batch_pack_score(
                fact=int(fact),
                typical=typical,
                watch=watch,
                departure=departure,
                title=title,
                description=description,
            )
            cat = f"BATCH_{code}_x{n_obj}"
        else:
            n_all, cat = new_score(
                typical=typical,
                watch=watch,
                departure=departure,
                spent_hours=spent_h,
                assignee=assignee,
                apply_complications=False,
                apply_investigation_gate=False,
            )
            if not has_score:
                non_mfc_unscored += 1

        cat_counter[cat] += 1

        n_scored = n_all if has_score else 0
        n_no_mfc = 0 if mfc else n_all

        if mfc_bulk:
            n_xlong, n_gate = 0, 0
        elif compensator or (batch and has_score):
            n_xlong = n_all
            n_gate = n_all
        else:
            n_xlong, _ = new_score(
                typical=typical,
                watch=watch,
                departure=departure,
                spent_hours=spent_h,
                assignee=assignee,
                apply_complications=True,
                apply_investigation_gate=False,
            )
            n_gate, _ = new_score(
                typical=typical,
                watch=watch,
                departure=departure,
                spent_hours=spent_h,
                assignee=assignee,
                apply_complications=False,
                apply_investigation_gate=True,
            )

        values = {
            "fact": fact_pts,
            "fact_duty_x2": fact_x2,
            "new_all": float(n_all),
            "new_scored_only": float(n_scored),
            "new_no_mfc": float(n_no_mfc),
            "new_all_xlong": float(n_xlong),
            "new_all_gate": float(n_gate),
        }

        for mode, pts in values.items():
            for bucket in (by_am[mode][(assignee, mk)], by_a[mode][assignee], by_m[mode][mk], totals[mode]):
                bucket["points"] += pts
                bucket["tickets"] += 1
                if watch:
                    bucket["points_duty"] += pts
                    bucket["tickets_duty"] += 1
                else:
                    bucket["points_reg"] += pts
                    bucket["tickets_reg"] += 1
                if has_score:
                    bucket["scored_tickets"] += 1
                    if watch:
                        bucket["scored_duty"] += 1
                    else:
                        bucket["scored_reg"] += 1

        if has_score:
            dlt = float(n_scored) - float(fact)
            drv_key = classify_scored_driver(
                compensator=compensator,
                batch=batch,
                fact=int(fact),
                new_pts=int(n_scored),
            )
            sd = scored_drv[assignee]
            sd["fact_pts"] += float(fact)
            sd["new_pts"] += float(n_scored)
            block = sd[drv_key]
            block["pts"] += dlt
            block["n"] += 1
            if abs(dlt) >= 15 and len(block["examples"]) < 3:
                block["examples"].append(
                    {
                        "title": (rec["title"] or "")[:50],
                        "fact": int(fact),
                        "new": int(n_scored),
                        "typical": (typical or "")[:40],
                    }
                )

    # --- Build markdown report ---
    meta_path = DATA / "fetch_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    months = sorted(by_m["fact"].keys())
    # Focus assignees: those with fact points > 0 or many tickets
    assignees = sorted(
        by_a["fact"].keys(),
        key=lambda a: -by_a["fact"][a]["points"],
    )
    # Drop noise: keep people with >= 20 tickets or any fact points; exclude noise assignees
    main_assignees = [
        a
        for a in assignees
        if a not in EXCLUDE_ASSIGNEES
        and (by_a["fact"][a]["tickets"] >= 20 or by_a["fact"][a]["points"] > 0)
    ]

    explanations = {
        a: build_explanation_text(a, scored_drv[a], RUB_PER_POINT) for a in main_assignees
    }

    lines: list[str] = []
    def w(s: str = "") -> None:
        lines.append(s)

    fact_pts = totals["fact"]["points"]
    fact_rub = fact_pts * RUB_PER_POINT
    new_all_pts = totals["new_all"]["points"]
    new_all_rub = new_all_pts * RUB_PER_POINT
    new_sc_pts = totals["new_scored_only"]["points"]
    new_sc_rub = new_sc_pts * RUB_PER_POINT
    new_nm_pts = totals["new_no_mfc"]["points"]
    new_nm_rub = new_nm_pts * RUB_PER_POINT
    new_xl_pts = totals["new_all_xlong"]["points"]
    new_xl_rub = new_xl_pts * RUB_PER_POINT
    fact_x2_pts = totals["fact_duty_x2"]["points"]
    fact_x2_rub = fact_x2_pts * RUB_PER_POINT
    high_sum = sum(x[2] for x in high_cut)

    w("# Сравнительный анализ премий: факт vs новый подход")
    w()
    w(f"**Период выгрузки:** {meta.get('since', '?')} — {meta.get('until', '?')} ({meta.get('months', '?')} мес.)")
    w(f"**Заявок в выборке:** {meta.get('list_count', len(details))}")
    w(f"**Курс:** 1 балл = **{RUB_PER_POINT} ₽**")
    w(f"**Дата расчёта:** {datetime.now().strftime('%Y-%m-%d')}")
    w()
    w("> Документ моделирует «что было бы», если бы нормативный справочник (docs/01–04, 15) уже действовал на этой выгрузке. Это **прогноз/симуляция**, не утверждённый расчёт ФОТ.")
    w()

    w("## 1. Вывод для руководителя (кратко)")
    w()
    delta_all = new_all_rub - fact_rub
    delta_sc = new_sc_rub - fact_rub
    delta_nm = new_nm_rub - fact_rub
    w("| Вопрос | Ответ по модели |")
    w("|--------|-----------------|")
    w(
        f"| Расход премий, если считать нормы на заявки с работой (техbulk MFC без баллов = 0, оплата через дневной компенсатор) | "
        f"**{fmt_rub(new_all_rub)} ₽** vs факт **{fmt_rub(fact_rub)} ₽** ({pct(new_all_rub, fact_rub)}, {fmt_delta(delta_all)} ₽) |"
    )
    w(
        f"| Сравнение «яблоко к яблоку»: нормы только там, где сейчас уже стоят баллы | "
        f"**{fmt_rub(new_sc_rub)} ₽** ({pct(new_sc_rub, fact_rub)}, {fmt_delta(delta_sc)} ₽) |"
    )
    w(
        f"| Если **весь MFC-контур вынести** из премиальной базы (только не-MFC) | "
        f"**{fmt_rub(new_nm_rub)} ₽** ({pct(new_nm_rub, fact_rub)} к полному факту) |"
    )
    w(
        f"| Верхняя оценка с эвристикой `X_LONG` (≥{X_LONG_HOURS:.0f} ч) | "
        f"**{fmt_rub(new_xl_rub)} ₽** ({pct(new_xl_rub, fact_rub)}) |"
    )
    w()

    # Interpret pain
    if abs(delta_sc) / max(fact_rub, 1) < 0.1:
        pain = "умеренная: на сопоставимом объёме (где баллы уже ставили) ФОТ премий меняется слабо"
    elif delta_sc < 0:
        pain = "в сторону **снижения** на сопоставимом объёме — больнее тем, у кого был хвост высоких самооценок (раскатки/запуски), не из‑за техbulk MFC"
    else:
        pain = "в сторону **роста** на сопоставимом объёме — в основном из‑за подъёма «типовых 5→нормы» и консультаций C15"

    w(f"**Ожидание по «болезненности»:** {pain}.")
    w()
    months_n = max(len(months), 1)
    w("| Ориентир | Факт | Новый (scored) | Новый (все, с правилом MFC) |")
    w("|----------|-----:|---------------:|---------------------------:|")
    w(
        f"| За ~6 мес | {fmt_rub(fact_rub)} ₽ | {fmt_rub(new_sc_rub)} ₽ | {fmt_rub(new_all_rub)} ₽ |"
    )
    w(
        f"| В среднем на месяц | {fmt_rub(fact_rub / months_n)} ₽ | "
        f"{fmt_rub(new_sc_rub / months_n)} ₽ | {fmt_rub(new_all_rub / months_n)} ₽ |"
    )
    w()
    w("### Вердикт по расходу на премии")
    w()
    w(
        f"- **Базовый прогноз для фонда (замена самооценки на нормы на том же объёме scored):** "
        f"расход **изменится на {fmt_delta(delta_sc)} ₽** за период "
        f"(~**{fmt_delta(delta_sc / months_n)} ₽/мес**, {pct(new_sc_rub, fact_rub)})."
    )
    w(
        f"- **MFC техзакрытия без баллов — это норма процесса**, не «дыра». Их **{mfc_unscored}**; "
        f"оплата идёт через дневные компенсаторы («МФС. Заявки, звонки» и аналоги): "
        f"найдено **{mfc_comp_n}** шт., факт **{fmt_rub(mfc_comp_fact_pts * RUB_PER_POINT)} ₽**, "
        f"по норме T5×Nтех/день → **{fmt_rub(mfc_comp_new_pts * RUB_PER_POINT)} ₽** "
        f"({pct(mfc_comp_new_pts * RUB_PER_POINT, max(mfc_comp_fact_pts * RUB_PER_POINT, 1))})."
    )
    w(
        f"- Сценарий «нормы на все» после правки MFC ≈ **{fmt_rub(new_all_rub)} ₽** ({pct(new_all_rub, fact_rub)}) — "
        f"рост возможен только за счёт **не-MFC** заявок без баллов ({non_mfc_unscored}), не за счёт техbulk."
    )
    w()
    w("Главные эффекты нового подхода в деньгах:")
    w()
    w(
        f"1. **Пакеты по объектам** (раскатка/обновление/запуск с перечнем касс) считаются как "
        f"**база × N**, а не срезаются до одной нормы — это не «накрутка», а объём."
    )
    w(
        f"2. **Срез** остаётся только у крупных баллов **без** признаков пакета "
        f"({len(high_cut)} заявок, **{fmt_rub(high_sum * RUB_PER_POINT)} ₽**)."
    )
    w(
        f"3. **MFC:** техbulk без баллов = 0; компенсатор = "
        f"**{MFC_TECH_POINTS} × число техзаявок за день**."
    )
    w("4. **Дежурство ×2** в новой модели применяется к *норме*, а не к свободной цифре.")
    w("5. Перераспределение между людьми сильнее, чем сдвиг фонда: выигрывают те, у кого много «честных» 5–10 на C15-категориях.")
    w()

    w("## 1a. Находка по MFC (компенсирующая заявка)")
    w()
    w("В выгрузке подтверждается правило процесса:")
    w()
    w("1. Массовые технические заявки MFC часто **без баллов** — это ожидаемо.")
    w("2. Почти каждый день есть **одна (или несколько) сводных заявок** вида «МФС. Заявки, звонки» с крупным баллом — компенсация объёма.")
    w(
        f"3. В модели: {mfc_comp_n} компенсаторов, {mfc_bulk_zeroed} техbulk обнулены в новом подходе, "
        f"корреляция числа техзаявок дня с суммой компенсатора на практике умеренная (~0.46), "
        f"медиана «баллов компенсатора / техзаявка» ≈ 5 → норма T5×N согласована с фактом."
    )
    w()
    w("## 1b. Пакетные заявки (N объектов в одной)")
    w()
    w(
        "Крупный балл (часто ≥100) — как правило **не свободная самооценка**, а одна заявка "
        "с перечнем однотипных работ по объектам (обновление ПО, раскатка, запуск, тарифы на кассы…). "
        "Оценка должна соответствовать **числу объектов × норма категории**."
    )
    w()
    w("В симуляции:")
    w()
    w("- детект пакета: маркеры в теме (апдейт/раскатка/запуск/…) или ≥3 объекта в описании/таблице, или typical «Доп. настройки»/оборудование при балле ≥100;")
    w("- норма = `(база T5/C15/S30 × коэффициент дежурства) × N`;")
    w("- N берётся из описания, иначе восстанавливается из факта (`round(факт / единица)`), поэтому пакет почти не «режется».")
    w()

    w("## 2. Методология")
    w()
    w("### 2.1. Факт (как в выгрузке)")
    w()
    w("- Берётся поле `ticket_weight` (баллы, которые поставил инженер).")
    w("- Нет баллов → **0 ₽** по этой заявке.")
    w("- Множитель дежурства **повторно не начисляется**: в данных медиана на дежурстве уже 10 vs 5 вне дежурства — часть ×2, похоже, уже в выборе балла. Для чувствительности есть сценарий `fact_duty_x2` (если бы ×2 начисляли сверху на уже проставленный балл).")
    w(f"- Премия ≈ баллы × {RUB_PER_POINT} ₽.")
    w()
    w("### 2.2. Новый подход (симуляция)")
    w()
    w("Формула из принципов:")
    w()
    w("```")
    w("если выезд: итого = 60 × (2 если дежурство else 1)")
    w("иначе:     итого = (база × N + осложнение) × (2 если дежурство else 1)")
    w("```")
    w()
    w("| Элемент | Как смоделировано |")
    w("|---------|-------------------|")
    w("| База | `typical` → T5=5 / C15=15 / S30=30 (таблица ниже) |")
    w("| Пустой `typical` | T5=5 (консервативно; **не** для MFC-техbulk) |")
    w("| «Другое» | C15=15 (пока нет «Нестандарт» + дыр каталога); **не** свободные 500–1000 |")
    w(
        f"| **Пакет по объектам** (раскатка/апдейт/запуск/…) | `база × N` объектов; N из описания или из факта |"
    )
    w(
        f"| **MFC техbulk** (без баллов, не компенсатор) | **0** — оплата через дневной пакет |"
    )
    w(
        f"| **MFC компенсатор** (заголовок «…Заявки…», клиент MFC) | `{MFC_TECH_POINTS}` × число техзаявок MFC за тот же день (`MFC_DAY`) |"
    )
    w(f"| Выезд (`departure`) | **только {VISIT_POINTS_DEFAULT}** (typical / N / осложнение не суммируются) |")
    w("| Осложнение | уровни **+15** / **+30** + текст (в базовой симуляции: X_LONG≈+15 при ≥2 ч) |")
    w("| Дежурство (`watch`) | ×2 к сумме нормы |")
    w(f"| Осложнение `X_LONG` (сценарий) | +{X_LONG}, если `spent_time_total` ≥ {X_LONG_HOURS:.0f} ч |")
    w("| Гейт расследований (сценарий) | `Расхождение…` = S30 только целевым; иначе T5 (черновой список целевых) |")
    w("| Сегменты премии (конвейер/пул) | **не меняют рубли в этой таблице**, но меняют интерпретацию «кто молодец» — см. § 7 |")
    w()
    w("#### Маппинг типовых проблем → база")
    w()
    w("| Типовая проблема | Код | База |")
    w("|-----------------|-----|-----:|")
    for name, (code, pts) in sorted(TYPICAL_BASE.items(), key=lambda x: (x[1][1], x[0])):
        w(f"| {name} | `{code}` | {pts} |")
    w(f"| *(пусто)* | `T5` | {DEFAULT_EMPTY[1]} |")
    w()
    w("### 2.3. Сценарии")
    w()
    w("| Код | Смысл |")
    w("|-----|--------|")
    w("| **fact** | Текущие баллы × 15 ₽ |")
    w("| **fact_duty_x2** | Факт, но если `watch` — ещё ×2 (верхняя оценка текущего ФОТ, если ×2 платят сверху) |")
    w("| **new_all** | Нормы на заявки с работой; MFC-техbulk без баллов = 0; компенсатор = T5×N |")
    w("| **new_scored_only** | Нормы только на заявки, где сейчас уже были баллы (компенсатор входит) |")
    w("| **new_no_mfc** | Нормы только на **не-MFC** компании |")
    w("| **new_all_xlong** | new_all + эвристика X_LONG (в этой выгрузке `spent_time_total` ≥ 2 ч почти не встречается → совпадает с new_all) |")
    w("| **new_all_gate** | new_all + гейт расследований |")
    w()

    w("## 3. Итог по компании за период")
    w()
    w("| Сценарий | Баллы | Премия, ₽ | Δ к fact, ₽ | Δ % |")
    w("|----------|------:|----------:|------------:|----:|")
    for mode, label in [
        ("fact", "Факт (ticket_weight)"),
        ("fact_duty_x2", "Факт + ×2 поверх watch"),
        ("new_all", "Новый: все заявки"),
        ("new_scored_only", "Новый: только где были баллы"),
        ("new_no_mfc", "Новый: без MFC в базе"),
        ("new_all_xlong", "Новый: все + X_LONG"),
        ("new_all_gate", "Новый: все + гейт расслед."),
    ]:
        pts = totals[mode]["points"]
        rub = pts * RUB_PER_POINT
        dlt = rub - fact_rub
        w(f"| {label} | {fmt_rub(pts)} | {fmt_rub(rub)} | {fmt_delta(dlt)} | {pct(rub, fact_rub)} |")
    w()
    w(
        f"Справочно: заявок без баллов в периоде — **{mfc_unscored + non_mfc_unscored}** "
        f"(MFC без баллов: {mfc_unscored}, не-MFC без баллов: {non_mfc_unscored})."
    )
    w(f"Заявок с фактом ≥ 100 баллов (кандидат на срезку): **{len(high_cut)}**.")
    w()
    w(
        f"Сумма баллов в хвосте ≥100: **{fmt_rub(high_sum)}** ≈ **{fmt_rub(high_sum * RUB_PER_POINT)} ₽** "
        f"({100 * high_sum / max(fact_pts, 1):.1f}% фактического фонда баллов)."
    )
    w()

    w("## 4. По месяцам (вся команда)")
    w()
    w("| Месяц | Заявок | Факт, ₽ | Новый (все), ₽ | Новый (только scored), ₽ | Новый без MFC, ₽ | Δ scored vs fact |")
    w("|-------|-------:|--------:|---------------:|-------------------------:|-----------------:|-----------------:|")
    for mk in months:
        t = by_m["fact"][mk]["tickets"]
        fr = by_m["fact"][mk]["points"] * RUB_PER_POINT
        na = by_m["new_all"][mk]["points"] * RUB_PER_POINT
        ns = by_m["new_scored_only"][mk]["points"] * RUB_PER_POINT
        nm = by_m["new_no_mfc"][mk]["points"] * RUB_PER_POINT
        w(
            f"| {mk} | {t} | {fmt_rub(fr)} | {fmt_rub(na)} | {fmt_rub(ns)} | {fmt_rub(nm)} | "
            f"{fmt_delta(ns - fr)} ({pct(ns, fr)}) |"
        )
    w()
    # Monthly totals row
    w(
        f"| **Итого** | {int(totals['fact']['tickets'])} | {fmt_rub(fact_rub)} | "
        f"{fmt_rub(new_all_rub)} | {fmt_rub(new_sc_rub)} | {fmt_rub(new_nm_rub)} | "
        f"{fmt_delta(delta_sc)} ({pct(new_sc_rub, fact_rub)}) |"
    )
    w()

    w("## 5. По сотрудникам за весь период")
    w()
    w("Сортировка по фактической сумме баллов. «Боль» = падение new_scored_only относительно fact.")
    w()
    w(
        "Две статьи: **обычные** (чекбокс дежурство = нет) и **дежурство** (чекбокс = да) — "
        f"отдельные контуры премии; 1 балл = {RUB_PER_POINT} ₽."
    )
    w()
    w(
        "| Сотрудник | Обыч. факт, ₽ | Обыч. новый, ₽ | Δ обыч. | Деж. факт, ₽ | Деж. новый, ₽ | Δ деж. | Итого Δ scored |"
    )
    w("|-----------|-------------:|---------------:|--------:|-------------:|--------------:|-------:|----------------:|")
    for a in main_assignees:
        fa = by_a["fact"][a]
        ns = by_a["new_scored_only"][a]
        fr = fa["points_reg"] * RUB_PER_POINT
        fd = fa["points_duty"] * RUB_PER_POINT
        nsr = ns["points_reg"] * RUB_PER_POINT
        nsd = ns["points_duty"] * RUB_PER_POINT
        w(
            f"| {a} | {fmt_rub(fr)} | {fmt_rub(nsr)} | {fmt_delta(nsr - fr)} | "
            f"{fmt_rub(fd)} | {fmt_rub(nsd)} | {fmt_delta(nsd - fd)} | "
            f"{fmt_delta((nsr + nsd) - (fr + fd))} |"
        )
    w()

    # Who gains / loses
    deltas = []
    for a in main_assignees:
        fr = by_a["fact"][a]["points"] * RUB_PER_POINT
        ns = by_a["new_scored_only"][a]["points"] * RUB_PER_POINT
        if fr == 0 and ns == 0:
            continue
        deltas.append((a, ns - fr, fr, ns))
    losers = sorted([x for x in deltas if x[1] < 0], key=lambda x: x[1])[:8]
    winners = sorted([x for x in deltas if x[1] > 0], key=lambda x: -x[1])[:8]

    w("### 5.1. Кому больнее (new_scored_only − fact)")
    w()
    if not losers:
        w("_Нет падений на основном составе._")
    else:
        w("| Сотрудник | Факт, ₽ | Новый scored, ₽ | Δ, ₽ |")
        w("|-----------|--------:|----------------:|-----:|")
        for a, dlt, fr, ns in losers:
            w(f"| {a} | {fmt_rub(fr)} | {fmt_rub(ns)} | {fmt_delta(dlt)} |")
    w()
    w("### 5.2. Кто выигрывает на том же объёме scored")
    w()
    if not winners:
        w("_Нет роста._")
    else:
        w("| Сотрудник | Факт, ₽ | Новый scored, ₽ | Δ, ₽ |")
        w("|-----------|--------:|----------------:|-----:|")
        for a, dlt, fr, ns in winners:
            w(f"| {a} | {fmt_rub(fr)} | {fmt_rub(ns)} | {fmt_delta(dlt)} |")
    w()

    w("### 5.3. Почему меняется scored у каждого инженера")
    w()
    w(
        "Разложение Δ scored по драйверам: срез хвоста ≥100, компенсатор MFC, "
        "рост/снижение по нормам каталога (только заявки, где баллы уже стояли)."
    )
    w()
    for a in main_assignees:
        ex = explanations[a]
        w(f"#### {a}")
        w()
        w(ex["lead"])
        w()
        w(ex["dominant"])
        w()
        if ex["parts"]:
            for p in ex["parts"]:
                w(
                    f"- **{fmt_delta(p['delta_rub'])} ₽** — {p['title']} ({p['n']} заяв.): {p['why']}"
                )
                if p.get("examples"):
                    w(f"  - Примеры: {'; '.join(p['examples'])}")
            w()
        else:
            w("_Нет заметных драйверов._")
            w()

    w("## 6. По сотрудникам × месяцы (факт vs new_scored_only)")
    w()
    w("Для читаемости — сотрудники с фактом ≥ 5 000 ₽ за период (или топ по заявкам).")
    w()

    focus = [
        a
        for a in main_assignees
        if by_a["fact"][a]["points"] * RUB_PER_POINT >= 5000 or by_a["fact"][a]["tickets"] >= 200
    ]

    for a in focus:
        w(f"### {a}")
        w()
        w("| Месяц | Заявок | Факт, ₽ | Новый scored, ₽ | Новый все, ₽ | Δ scored |")
        w("|-------|-------:|--------:|----------------:|-------------:|---------:|")
        for mk in months:
            key = (a, mk)
            if key not in by_am["fact"] and key not in by_am["new_all"]:
                continue
            fa = by_am["fact"][key]
            if fa["tickets"] == 0 and by_am["new_all"][key]["tickets"] == 0:
                continue
            fr = fa["points"] * RUB_PER_POINT
            ns = by_am["new_scored_only"][key]["points"] * RUB_PER_POINT
            na = by_am["new_all"][key]["points"] * RUB_PER_POINT
            t = int(fa["tickets"] or by_am["new_all"][key]["tickets"])
            w(
                f"| {mk} | {t} | {fmt_rub(fr)} | {fmt_rub(ns)} | {fmt_rub(na)} | "
                f"{fmt_delta(ns - fr)} |"
            )
        fr_t = by_a["fact"][a]["points"] * RUB_PER_POINT
        ns_t = by_a["new_scored_only"][a]["points"] * RUB_PER_POINT
        na_t = by_a["new_all"][a]["points"] * RUB_PER_POINT
        w(
            f"| **Итого** | {int(by_a['fact'][a]['tickets'])} | {fmt_rub(fr_t)} | "
            f"{fmt_rub(ns_t)} | {fmt_rub(na_t)} | {fmt_delta(ns_t - fr_t)} |"
        )
        w()

    w("## 7. Что это значит для расхода на премии")
    w()
    w("### 7.1. Три развилки решения")
    w()
    w("| Решение | Влияние на ФОТ | Комментарий |")
    w("|---------|----------------|-------------|")
    w(
        f"| Нормы + правило MFC (техbulk=0, компенсатор=T5×N) | "
        f"ФОТ → ~{fmt_rub(new_all_rub)} ₽ ({pct(new_all_rub, fact_rub)}) | "
        f"**Базовая модель этого отчёта** — отражает текущий процесс MFC |"
    )
    w(
        f"| Полностью вынести MFC из балльной премии | "
        f"ориентир ~{fmt_rub(new_nm_rub)} ₽ на не-MFC | "
        f"Только если компенсатор/пакет MFC оплачивается иначе |"
    )
    w(
        f"| Сначала заменить только самооценку там, где баллы уже ставят | "
        f"~{fmt_rub(new_sc_rub)} ₽ ({pct(new_sc_rub, fact_rub)}) | "
        f"Близко к new_all после учёта MFC; удобно для теневого периода |"
    )
    w()
    w("### 7.2. Ожидания как руководителю")
    w()
    if delta_sc < 0:
        w(
            f"- На **сопоставимом объёме** (scored) модель даёт **снижение** фонда примерно на "
            f"**{fmt_rub(abs(delta_sc))} ₽** ({pct(new_sc_rub, fact_rub)}) за ~6 мес — "
            f"т.е. порядка **{fmt_rub(abs(delta_sc) / max(len(months), 1))} ₽/мес**."
        )
    else:
        w(
            f"- На **сопоставимом объёме** (scored) модель даёт **рост** фонда примерно на "
            f"**{fmt_rub(delta_sc)} ₽** ({pct(new_sc_rub, fact_rub)}) за период."
        )
    w(
        f"- После учёта компенсатора MFC сценарий «новый все» ≈ **{fmt_rub(new_all_rub)} ₽** "
        f"({pct(new_all_rub, fact_rub)}) — техbulk больше не раздувает фонд."
    )
    w("- **Болезненность точечная:** сильнее всего у тех, кто закрывал массовые раскатки/запуски крупными цифрами при коротком времени; у «честного» конвейера 5–10 изменение мягкое или в плюс (C15 на консультации/доп.настройки). Дневной пакет MFC при норме T5×N близок к текущей медиане.")
    w("- **Политика сегментов** (конвейер vs пул vs расследования) почти не меняет сумму в рублях в этой симуляции, но меняет справедливость внутри команды — без неё формально «правильные» баллы всё равно будут толкать людей на удобный поток.")
    w("- Дежурства: при переходе на ×2 от **нормы** по табелю (не от самооценки) ожидайте пересчёт дежурного контура 1,5 недели отдельно от месячного.")
    w()
    w("### 7.3. Рекомендуемый порядок внедрения (чтобы не ударить ФОТ и людей)")
    w()
    w("1. Утвердить маппинг typical→база и **явный список конвейерных клиентов** (IFCM, MFC, …).")
    w("2. MFC: зафиксировать в регламенте «техbulk без баллов + дневной компенсатор»; в нормах — `MFC_DAY = T5 × N` (или иная ставка), не начислять баллы на каждую техзаявку.")
    w("3. Включить нормы на нативном контуре; параллельно 1–2 месяца **теневой расчёт** (как этот отчёт) без смены выплат.")
    w("4. Срезать свободный select; крупные работы (раскатка/запуск) — отдельные категории с нормой + аудит, не 500–1000 «от себя».")
    w("5. Потом — трек расследований и гейт целевых (docs/15).")
    w()

    w("## 8. Ограничения модели")
    w()
    w("- Каталог T5/C15/S30 — **черновик**; смена консультации с факт-медианы 5 на C15=15 заметно двигает фонд.")
    w("- Выезд: только +60 при `departure` (без суммы с typical).")
    w("- Осложнения почти не восстановить из API → `X_LONG` грубый.")
    w("- Список целевых для расследований — **заглушка** для чувствительности, не HR-решение.")
    w("- Не моделировались качество, SLA-после-взятия, срезание по аудиту.")
    w("- Часть заявок без `completed_at` могла уйти в `updated_at` (см. скрипт).")
    w()
    w("## 9. Как пересчитать")
    w()
    w("```bash")
    w("python scripts/compare_bonus_models.py")
    w("# → analysis/bonus-comparison.md")
    w("# → analysis/bonus-comparison.html  (по инженерам × месяцы)")
    w("# → analysis/bonus-comparison.json")
    w("```")
    w()
    w("---")
    w()
    w("*Скрипт: `scripts/compare_bonus_models.py`. Правила: `docs/00`–`04`, `11`, `15`.*")

    report_path = OUT / "bonus-comparison.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    html_path = OUT / "bonus-comparison.html"
    html_path.write_text(
        render_bonus_html(
            meta=meta,
            months=months,
            main_assignees=main_assignees,
            by_a=by_a,
            by_am=by_am,
            by_m=by_m,
            totals=totals,
            rub=RUB_PER_POINT,
            explanations=explanations,
        ),
        encoding="utf-8",
    )

    # JSON summary for reuse
    by_assignee_month: dict[str, dict[str, dict]] = {}
    for a in main_assignees:
        by_assignee_month[a] = {}
        for mk in months:
            key = (a, mk)
            tickets = int(by_am["fact"][key]["tickets"] or by_am["new_all"][key]["tickets"])
            if tickets == 0:
                continue
            by_assignee_month[a][mk] = {
                m: {
                    "points": by_am[m][key]["points"],
                    "rub": by_am[m][key]["points"] * RUB_PER_POINT,
                    "tickets": by_am[m][key]["tickets"],
                    "scored_tickets": by_am[m][key]["scored_tickets"],
                }
                for m in ("fact", "new_scored_only", "new_all", "new_no_mfc")
            }

    summary = {
        "rub_per_point": RUB_PER_POINT,
        "meta": meta,
        "totals": {
            m: {
                "points": totals[m]["points"],
                "rub": totals[m]["points"] * RUB_PER_POINT,
                "points_reg": totals[m]["points_reg"],
                "rub_reg": totals[m]["points_reg"] * RUB_PER_POINT,
                "points_duty": totals[m]["points_duty"],
                "rub_duty": totals[m]["points_duty"] * RUB_PER_POINT,
                "tickets": totals[m]["tickets"],
                "tickets_reg": totals[m]["tickets_reg"],
                "tickets_duty": totals[m]["tickets_duty"],
            }
            for m in modes
        },
        "by_month": {
            mk: {
                m: {
                    "points": by_m[m][mk]["points"],
                    "rub": by_m[m][mk]["points"] * RUB_PER_POINT,
                    "tickets": by_m[m][mk]["tickets"],
                }
                for m in modes
            }
            for mk in months
        },
        "by_assignee": {
            a: {
                m: {
                    "points": by_a[m][a]["points"],
                    "rub": by_a[m][a]["points"] * RUB_PER_POINT,
                    "points_reg": by_a[m][a]["points_reg"],
                    "rub_reg": by_a[m][a]["points_reg"] * RUB_PER_POINT,
                    "points_duty": by_a[m][a]["points_duty"],
                    "rub_duty": by_a[m][a]["points_duty"] * RUB_PER_POINT,
                    "tickets": by_a[m][a]["tickets"],
                    "tickets_reg": by_a[m][a]["tickets_reg"],
                    "tickets_duty": by_a[m][a]["tickets_duty"],
                    "scored_tickets": by_a[m][a]["scored_tickets"],
                }
                for m in modes
            }
            for a in main_assignees
        },
        "by_assignee_month": by_assignee_month,
        "explanations": explanations,
        "diagnostics": {
            "mfc_unscored": mfc_unscored,
            "non_mfc_unscored": non_mfc_unscored,
            "mfc_bulk_zeroed": mfc_bulk_zeroed,
            "mfc_compensators": mfc_comp_n,
            "mfc_comp_fact_points": mfc_comp_fact_pts,
            "mfc_comp_new_points": mfc_comp_new_pts,
            "mfc_tech_points_per_ticket": MFC_TECH_POINTS,
            "high_tail_count": len(high_cut),
            "high_tail_points": high_sum,
            "category_counts": dict(cat_counter),
            "skipped_no_month": skipped_no_month,
            "excluded_assignees": sorted(EXCLUDE_ASSIGNEES),
            "excluded_tickets": excluded_tickets,
        },
    }
    (OUT / "bonus-comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote {report_path}")
    print(f"Wrote {html_path}")
    print(f"fact_rub={fact_rub:.0f} new_all_rub={new_all_rub:.0f} new_scored_rub={new_sc_rub:.0f} new_no_mfc_rub={new_nm_rub:.0f}")
    print(f"delta_scored_pct={pct(new_sc_rub, fact_rub)} delta_all_pct={pct(new_all_rub, fact_rub)}")


if __name__ == "__main__":
    main()
