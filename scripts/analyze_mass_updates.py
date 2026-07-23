#!/usr/bin/env python3
"""Mass software-update tickets: volume, bonus share, auto-update reduction scenarios."""

from __future__ import annotations

import html as html_lib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "analysis"
OUT.mkdir(parents=True, exist_ok=True)

RUB = 15
EXCLUDE = {
    "(без ответственного)",
    "Елыков Денис",
    "Меркулов Игорь",
}

# Explicit mass-rollout markers in title
MASS_TITLE = (
    "апдейт",
    "update",
    "обновлен",
    "раскат",
    "спулер",
    "spooler",
    "fshtrih",
    "frontupdater",
    "front updater",
    "лого",
    "sdk",
    "скрипт",
    "установка по",
    "установка front",
)

# Fully/mostly removable by auto-update agent
AUTO_KILL = (
    "спулер",
    "spooler",
    "fshtrih",
    "frontupdater",
    "front updater",
    "лого",
    "sdk",
    "horeca",
)

# Likely removable for standard POS software packs
AUTO_LIKELY_EXTRA = (
    "апдейт",
    "update",
    "обновлен",
    "раскат",
    "скрипт",
    "установка по",
    "установка front",
)

# Often still needs a person even with auto-update
RESIDUAL_SPECIAL = ("ндс", "банк", "расхожден", "портал")
RESIDUAL_LAUNCH = ("запуск", "подготов", "моноблок", "фискал")


def load_company_names() -> dict[int, str]:
    names: dict[int, str] = {}
    path = DATA / "issues_list.jsonl"
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        c = row.get("company") or {}
        if c.get("id") and c.get("name"):
            names[int(c["id"])] = c["name"]
    return names


def to_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def is_mass_candidate(title: str, score: int | None) -> bool:
    t = (title or "").lower().replace("ё", "е")
    if any(m in t for m in MASS_TITLE):
        return True
    if (score or 0) >= 100 and any(x in t for x in ("по ", "фронт", "чз", "касс", "драйвер")):
        return True
    return False


def auto_bucket(title: str) -> str:
    t = (title or "").lower().replace("ё", "е")
    if any(x in t for x in RESIDUAL_SPECIAL) and not any(x in t for x in AUTO_KILL):
        return "residual_special"
    if any(x in t for x in RESIDUAL_LAUNCH) and not any(x in t for x in AUTO_KILL):
        return "residual_launch"
    if any(x in t for x in AUTO_KILL):
        return "auto_kill"
    if any(x in t for x in AUTO_LIKELY_EXTRA):
        return "auto_likely"
    return "auto_likely"


def fmt_rub(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def main() -> None:
    company_names = load_company_names()
    meta_path = DATA / "fetch_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    all_n = 0
    all_scored_n = 0
    all_pts = 0
    by_a_all: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "pts": 0})

    mass: list[dict] = []

    for path in Path(DATA / "issues").glob("*.json"):
        if path.name.startswith("._"):
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        a = (d.get("assignee") or {}).get("name") or "(без ответственного)"
        if a in EXCLUDE:
            continue
        all_n += 1
        by_a_all[a]["n"] += 1
        pm = {p.get("code"): p.get("value") for p in (d.get("parameters") or [])}
        sci = to_int(pm.get("ticket_weight"))
        if sci is not None:
            all_scored_n += 1
            all_pts += sci
            by_a_all[a]["pts"] += sci

        title = d.get("title") or ""
        if not is_mass_candidate(title, sci):
            continue
        bucket = auto_bucket(title)
        typ = pm.get("typical")
        if isinstance(typ, list):
            typ = typ[0] if typ else None
        completed = d.get("completed_at") or d.get("updated_at") or ""
        cid = d.get("company_id")
        cname = company_names.get(int(cid), "") if cid is not None else ""
        mass.append(
            {
                "id": d.get("id"),
                "assignee": a,
                "score": sci or 0,
                "has_score": sci is not None,
                "title": title,
                "typical": typ or "",
                "bucket": bucket,
                "month": completed[:7],
                "watch": bool(pm.get("watch")),
                "company": cname,
            }
        )

    mass_n = len(mass)
    mass_pts = sum(r["score"] for r in mass)
    mass_rub = mass_pts * RUB
    hi = [r for r in mass if r["score"] >= 100]
    hi_pts = sum(r["score"] for r in hi)

    by_bucket: dict[str, list] = defaultdict(list)
    for r in mass:
        by_bucket[r["bucket"]].append(r)

    kill = by_bucket["auto_kill"] + by_bucket["auto_likely"]
    resid = by_bucket["residual_special"] + by_bucket["residual_launch"]
    kill_pts = sum(r["score"] for r in kill)
    resid_pts = sum(r["score"] for r in resid)

    scenarios = [
        ("Оптимистичный", 0.90, 0.30, "стандартные раскатки почти уходят; редкие сбои/офлайн-точки"),
        ("Базовый", 0.75, 0.20, "большинство ПО/спулеров/лого авто; часть ручных доводок остаётся"),
        ("Консервативный", 0.60, 0.10, "авто только на типовых агентах; много кастомных пакетов вручную"),
    ]

    scenario_rows = []
    for name, p_k, p_r, note in scenarios:
        gone_n = int(round(len(kill) * p_k + len(resid) * p_r))
        gone_pts = int(round(kill_pts * p_k + resid_pts * p_r))
        scenario_rows.append(
            {
                "name": name,
                "note": note,
                "gone_n": gone_n,
                "gone_pts": gone_pts,
                "gone_rub": gone_pts * RUB,
                "remain_n": mass_n - gone_n,
                "remain_pts": mass_pts - gone_pts,
                "remain_rub": (mass_pts - gone_pts) * RUB,
                "share_pts_gone": 100 * gone_pts / max(all_pts, 1),
                "share_tickets_gone": 100 * gone_n / max(all_n, 1),
                "mass_shrink_pct": 100 * gone_n / max(mass_n, 1),
            }
        )

    # Per assignee
    by_a_mass: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "pts": 0, "auto_n": 0, "auto_pts": 0}
    )
    for r in mass:
        b = by_a_mass[r["assignee"]]
        b["n"] += 1
        b["pts"] += r["score"]
        if r["bucket"] in ("auto_kill", "auto_likely"):
            b["auto_n"] += 1
            b["auto_pts"] += r["score"]

    title_top = Counter(r["title"][:70] for r in mass).most_common(15)
    title_pts = {
        t: sum(r["score"] for r in mass if r["title"][:70] == t) for t, _ in title_top
    }

    # --- Markdown ---
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("# Массовые обновления ПО на объектах и эффект автообновления")
    w()
    w(
        f"**Период:** {meta.get('since', '?')} — {meta.get('until', '?')} · "
        f"**курс:** 1 балл = {RUB} ₽ · без строк «без ответственного» / Елыков / Меркулов"
    )
    w()
    w("## Вывод")
    w()
    w(
        f"За ~6 мес к **массовому/ручному обновлению ПО** отнесено **{mass_n}** заявок "
        f"(**{100 * mass_n / max(all_n, 1):.1f}%** всех заявок), но они дают "
        f"**{fmt_rub(mass_pts)}** баллов ≈ **{fmt_rub(mass_rub)} ₽** — "
        f"**{100 * mass_pts / max(all_pts, 1):.1f}%** всего премиального фонда баллов."
    )
    w()
    w(
        f"Из них с баллом ≥100: **{len(hi)}** заявок и **{fmt_rub(hi_pts)}** баллов "
        f"({100 * hi_pts / max(mass_pts, 1):.0f}% баллов этого контура) — типичная «большая самооценка» = пакет по объектам."
    )
    w()
    base = scenario_rows[1]
    w(
        f"**Базовый сценарий автообновления:** контур массовых обновлений сокращается примерно на "
        f"**{base['mass_shrink_pct']:.0f}%** заявок (−{base['gone_n']} шт.), "
        f"премиальный фонд −**{fmt_rub(base['gone_rub'])} ₽** "
        f"(−{base['share_pts_gone']:.1f}% всех баллов периода)."
    )
    w()

    w("## Что считаем «массовым обновлением»")
    w()
    w("Заявка попадает в выборку, если в теме есть маркеры раскатки/апдейта:")
    w()
    w(
        "`обновлен*`, `апдейт`, `update`, `раскат`, `спулер`/`spooler`/`fshtrih`, "
        "`frontupdater`, `лого`, `sdk`, `скрипт`, `установка ПО` / `установка front`, "
        "либо балл ≥100 при явных ПО/Фронт/ЧЗ в теме."
    )
    w()
    w("| Корзина (для автообновления) | Заявок | Баллы | ₽ | Смысл |")
    w("|------------------------------|-------:|------:|--:|-------|")
    labels = {
        "auto_kill": "Снимается автообновлением почти полностью (спулер, frontupdater, лого, sdk…)",
        "auto_likely": "Снимается на типовых пакетах ПО/Фронт/ЧЗ (останутся сбои и исключения)",
        "residual_special": "Часто останется вручную (НДС, банк, портал, спец. сверки)",
        "residual_launch": "Часто останется (запуск/подготовка/моноблок/фискализация)",
    }
    for key in ("auto_kill", "auto_likely", "residual_special", "residual_launch"):
        rs = by_bucket[key]
        pts = sum(r["score"] for r in rs)
        w(f"| {key} | {len(rs)} | {fmt_rub(pts)} | {fmt_rub(pts * RUB)} | {labels[key]} |")
    w(f"| **Итого mass** | **{mass_n}** | **{fmt_rub(mass_pts)}** | **{fmt_rub(mass_rub)}** | |")
    w()

    w("## Сценарии внедрения автообновления")
    w()
    w(
        "Доля «исчезнувших» заявок = `p_kill × (auto_kill+auto_likely) + p_resid × residual`. "
        "Оставшийся хвост — офлайн-точки, кастом, первая установка, разбор после неудачного авто."
    )
    w()
    w(
        "| Сценарий | Снимается заявок | −% mass-контура | −баллов | −₽ | −% фонда баллов | Остаток mass-заявок |"
    )
    w("|----------|-----------------:|----------------:|--------:|---:|----------------:|-------------------:|")
    for s in scenario_rows:
        w(
            f"| **{s['name']}** | {s['gone_n']} | {s['mass_shrink_pct']:.0f}% | "
            f"{fmt_rub(s['gone_pts'])} | {fmt_rub(s['gone_rub'])} | "
            f"{s['share_pts_gone']:.1f}% | {s['remain_n']} |"
        )
    w()
    for s in scenario_rows:
        w(f"- **{s['name']}:** {s['note']}")
    w()

    w("## Кто сейчас «кормится» этим контуром")
    w()
    w("| Сотрудник | Mass-заявок | Баллы mass | Доля его баллов | Из них autoable (kill+likely), ₽ |")
    w("|-----------|------------:|-----------:|----------------:|--------------------------------:|")
    for a, v in sorted(by_a_mass.items(), key=lambda x: -x[1]["pts"]):
        share = 100 * v["pts"] / max(by_a_all[a]["pts"], 1)
        w(
            f"| {a} | {v['n']} | {fmt_rub(v['pts'])} | {share:.0f}% | "
            f"{fmt_rub(v['auto_pts'] * RUB)} |"
        )
    w()
    w(
        "Сильнее всего затронуты **Ососков** (~20% его баллов), **Павлов** (~34%), "
        "**Петров** (~15% — раскатки MFC/лого/спулер). Конвейер Сушков/Синкин почти не зависит от этого контура."
    )
    w()

    w("## Топ формулировок")
    w()
    w("| N | Баллы | Тема |")
    w("|--:|------:|------|")
    for t, c in title_top:
        w(f"| {c} | {fmt_rub(title_pts[t])} | {t} |")
    w()

    w("## Что внедрять вместе с автообновлением")
    w()
    w("1. **Каталог:** отдельный typical «Массовое обновление / раскатка ПО» с нормой `T5×N` или `C15×N` и обязательным списком объектов.")
    w("2. **Автоагент:** закрывает типовые пакеты без заявки или создаёт заявку с N=успешных точек и минимальным весом / вне премии инженера.")
    w("3. **Ручной остаток:** только failed/offline/custom → обычная заявка с аудитом.")
    w("4. **Премия:** после выката авто ожидать снижение статьи «пакетные обновления» на порядок **0.2–0.4 млн ₽ / 6 мес** (базовый сценарий), точечно у 2–3 сотрудников.")
    w()
    w("---")
    w(f"*Сгенерировано {datetime.now().strftime('%Y-%m-%d %H:%M')} · `python scripts/analyze_mass_updates.py`*")

    (OUT / "mass-update-auto.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- HTML ---
    esc = html_lib.escape
    parts: list[str] = []
    parts.append(
        f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Массовые обновления ПО → автообновление</title>
  <style>
    :root {{
      --bg:#f4f5f7; --surface:#fff; --text:#1a1d23; --muted:#5c6570; --line:#e2e5ea;
      --accent:#1f4b7a; --ok:#1f6b3a; --warn:#8a5a00;
    }}
    body {{ margin:0; font-family:"Segoe UI",system-ui,sans-serif; background:var(--bg); color:var(--text); line-height:1.45; }}
    .wrap {{ max-width:1000px; margin:0 auto; padding:28px 20px 72px; }}
    h1 {{ font-size:1.45rem; margin:0 0 8px; }}
    h2 {{ font-size:1.1rem; margin:28px 0 10px; }}
    .lead {{ color:var(--muted); max-width:80ch; }}
    .banner {{ background:#1f4b7a; color:#fff; border-radius:12px; padding:16px 18px; margin-bottom:16px; }}
    .banner a {{ color:#cfe3ff; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:14px 0; }}
    @media(max-width:800px){{ .stats{{ grid-template-columns:1fr 1fr; }} }}
    .stat {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
    .stat .v {{ font-size:1.2rem; font-weight:700; color:var(--accent); }}
    .stat .l {{ font-size:.8rem; color:var(--muted); margin-top:4px; }}
    .card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; margin:14px 0; overflow:hidden; }}
    .card-h {{ padding:12px 16px; border-bottom:1px solid var(--line); font-weight:650; }}
    table {{ width:100%; border-collapse:collapse; font-size:.88rem; }}
    th,td {{ padding:8px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); background:#fafbfc; }}
    td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
    tr:last-child td {{ border-bottom:0; }}
    .ok {{ color:var(--ok); font-weight:650; }}
    .muted {{ color:var(--muted); font-size:.85rem; }}
    ul {{ color:var(--muted); }}
    footer {{ margin-top:36px; color:#8b939e; font-size:.8rem; border-top:1px solid var(--line); padding-top:14px; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="banner">
    <strong style="display:block;margin-bottom:6px">Массовые обновления ПО vs автообновление</strong>
    Период {esc(str(meta.get('since','?')))} — {esc(str(meta.get('until','?')))} ·
    1 балл = {RUB} ₽ · см. также <a href="bonus-comparison.html">bonus-comparison.html</a>
  </div>
  <h1>Ручные раскатки: объём и что уйдёт с автообновлением</h1>
  <p class="lead">
    Крупные самооценки часто = одна заявка на обновление ПО по списку объектов.
    Ниже — сколько таких заявок в выгрузке и как сократится контур, если типовые обновления пойдут агентом.
  </p>
  <div class="stats">
    <div class="stat"><div class="v">{mass_n}</div><div class="l">Заявок mass-update<br>({100*mass_n/max(all_n,1):.1f}% всех)</div></div>
    <div class="stat"><div class="v">{esc(fmt_rub(mass_rub))} ₽</div><div class="l">Премия в этом контуре<br>({100*mass_pts/max(all_pts,1):.1f}% фонда баллов)</div></div>
    <div class="stat"><div class="v">{len(hi)}</div><div class="l">Из них с баллом ≥100<br>({esc(fmt_rub(hi_pts*RUB))} ₽)</div></div>
    <div class="stat"><div class="v ok">−{base['mass_shrink_pct']:.0f}%</div><div class="l">Сокращение mass (базовый)<br>−{esc(fmt_rub(base['gone_rub']))} ₽</div></div>
  </div>
"""
    )

    parts.append('<div class="card"><div class="card-h">Корзины</div><table><thead><tr>')
    parts.append(
        "<th>Корзина</th><th class='num'>Заявок</th><th class='num'>Баллы</th><th class='num'>₽</th><th>Смысл</th></tr></thead><tbody>"
    )
    for key in ("auto_kill", "auto_likely", "residual_special", "residual_launch"):
        rs = by_bucket[key]
        pts = sum(r["score"] for r in rs)
        parts.append(
            f"<tr><td><code>{esc(key)}</code></td><td class='num'>{len(rs)}</td>"
            f"<td class='num'>{esc(fmt_rub(pts))}</td><td class='num'>{esc(fmt_rub(pts*RUB))}</td>"
            f"<td class='muted'>{esc(labels[key])}</td></tr>"
        )
    parts.append(
        f"<tr><td><b>Итого</b></td><td class='num'><b>{mass_n}</b></td>"
        f"<td class='num'><b>{esc(fmt_rub(mass_pts))}</b></td>"
        f"<td class='num'><b>{esc(fmt_rub(mass_rub))}</b></td><td></td></tr>"
    )
    parts.append("</tbody></table></div>")

    parts.append('<div class="card"><div class="card-h">Сценарии автообновления</div><table><thead><tr>')
    parts.append(
        "<th>Сценарий</th><th class='num'>− заявок</th><th class='num'>−% mass</th>"
        "<th class='num'>− ₽</th><th class='num'>−% фонда</th><th class='num'>Остаток mass</th></tr></thead><tbody>"
    )
    for s in scenario_rows:
        parts.append(
            f"<tr><td><b>{esc(s['name'])}</b><div class='muted'>{esc(s['note'])}</div></td>"
            f"<td class='num'>{s['gone_n']}</td><td class='num'>{s['mass_shrink_pct']:.0f}%</td>"
            f"<td class='num ok'>−{esc(fmt_rub(s['gone_rub']))}</td>"
            f"<td class='num'>{s['share_pts_gone']:.1f}%</td>"
            f"<td class='num'>{s['remain_n']}</td></tr>"
        )
    parts.append("</tbody></table></div>")

    parts.append('<div class="card"><div class="card-h">По сотрудникам</div><table><thead><tr>')
    parts.append(
        "<th>Сотрудник</th><th class='num'>Mass N</th><th class='num'>Mass ₽</th>"
        "<th class='num'>% его баллов</th><th class='num'>Autoable ₽</th></tr></thead><tbody>"
    )
    for a, v in sorted(by_a_mass.items(), key=lambda x: -x[1]["pts"]):
        share = 100 * v["pts"] / max(by_a_all[a]["pts"], 1)
        parts.append(
            f"<tr><td>{esc(a)}</td><td class='num'>{v['n']}</td>"
            f"<td class='num'>{esc(fmt_rub(v['pts']*RUB))}</td>"
            f"<td class='num'>{share:.0f}%</td>"
            f"<td class='num'>{esc(fmt_rub(v['auto_pts']*RUB))}</td></tr>"
        )
    parts.append("</tbody></table></div>")

    parts.append('<div class="card"><div class="card-h">Топ тем</div><table><thead><tr>')
    parts.append("<th class='num'>N</th><th class='num'>Баллы</th><th>Тема</th></tr></thead><tbody>")
    for t, c in title_top:
        parts.append(
            f"<tr><td class='num'>{c}</td><td class='num'>{esc(fmt_rub(title_pts[t]))}</td><td>{esc(t)}</td></tr>"
        )
    parts.append("</tbody></table></div>")

    parts.append(
        f"""<h2>Практический вывод для руководителя</h2>
  <ul>
    <li>Контур маленький по <b>штукам</b> (~{100*mass_n/max(all_n,1):.1f}% заявок), но заметный по <b>деньгам</b> (~{100*mass_pts/max(all_pts,1):.0f}% фонда).</li>
    <li>Автообновление бьёт не по конвейеру 5–10 баллов, а по пакетным раскаткам у Ососкова / Павлова / Петрова.</li>
    <li>Базовый ориентир экономии премии: <b>≈{esc(fmt_rub(base['gone_rub']))} ₽ за 6 мес</b> (−{base['mass_shrink_pct']:.0f}% mass-заявок).</li>
    <li>Ручной хвост (НДС/банк/запуски/фейлы авто) лучше сразу оформить отдельным typical + N объектов.</li>
  </ul>
  <footer>Сгенерировано {esc(datetime.now().strftime('%Y-%m-%d %H:%M'))} · python scripts/analyze_mass_updates.py</footer>
</div></body></html>"""
    )

    (OUT / "mass-update-auto.html").write_text("\n".join(parts), encoding="utf-8")

    summary = {
        "rub_per_point": RUB,
        "meta": meta,
        "all_tickets": all_n,
        "all_scored_points": all_pts,
        "mass_tickets": mass_n,
        "mass_points": mass_pts,
        "mass_rub": mass_rub,
        "high_ge_100": {"n": len(hi), "points": hi_pts, "rub": hi_pts * RUB},
        "buckets": {
            k: {
                "n": len(by_bucket[k]),
                "points": sum(r["score"] for r in by_bucket[k]),
                "rub": sum(r["score"] for r in by_bucket[k]) * RUB,
            }
            for k in ("auto_kill", "auto_likely", "residual_special", "residual_launch")
        },
        "scenarios": scenario_rows,
        "by_assignee": {
            a: {
                **v,
                "rub": v["pts"] * RUB,
                "auto_rub": v["auto_pts"] * RUB,
                "share_of_person_points_pct": 100 * v["pts"] / max(by_a_all[a]["pts"], 1),
            }
            for a, v in by_a_mass.items()
        },
    }
    (OUT / "mass-update-auto.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote {OUT / 'mass-update-auto.md'}")
    print(f"Wrote {OUT / 'mass-update-auto.html'}")
    print(
        f"mass_n={mass_n} mass_rub={mass_rub} share_pts={100*mass_pts/max(all_pts,1):.1f}% "
        f"base_save_rub={base['gone_rub']} shrink={base['mass_shrink_pct']:.0f}%"
    )


if __name__ == "__main__":
    main()
