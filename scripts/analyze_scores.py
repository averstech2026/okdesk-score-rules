#!/usr/bin/env python3
"""Analyze fetched Okdesk issues: scores, typical problems, streams."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DETAILS_DIR = DATA / "issues"
OUT = ROOT / "analysis"
OUT.mkdir(parents=True, exist_ok=True)


def param_map(detail: dict) -> dict:
    out = {}
    for p in detail.get("parameters") or []:
        out[p.get("code")] = p.get("value")
    return out


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def load_details() -> list[dict]:
    rows = []
    for path in sorted(DETAILS_DIR.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def load_company_names() -> dict[int, str]:
    """Map company_id -> name from list export (detail has only company_id)."""
    path = DATA / "issues_list.jsonl"
    names: dict[int, str] = {}
    if not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        company = row.get("company") or {}
        cid = company.get("id")
        cname = company.get("name")
        if cid is not None and cname:
            names[int(cid)] = cname
    return names


def to_int_score(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def main() -> None:
    details = load_details()
    if not details:
        raise SystemExit("No details in data/issues — run scripts/fetch_issues.py first")
    company_names = load_company_names()

    by_assignee_scores: dict[str, list[int]] = defaultdict(list)
    by_assignee_count: Counter = Counter()
    by_company_count: Counter = Counter()
    by_company_scores: dict[str, list[int]] = defaultdict(list)
    by_typical_scores: dict[str, list[int]] = defaultdict(list)
    by_typical_count: Counter = Counter()
    by_solution: Counter = Counter()
    score_dist: Counter = Counter()
    weight_missing = 0
    departure_n = 0
    watch_n = 0
    durations_h: list[float] = []
    high_score_short: list[dict] = []
    month_scores: dict[str, Counter] = defaultdict(Counter)
    assignee_company: dict[str, Counter] = defaultdict(Counter)

    flat_rows = []

    for d in details:
        pm = param_map(d)
        score = to_int_score(pm.get("ticket_weight"))
        typical = pm.get("typical") or "(не указано)"
        sols = pm.get("solution_method") or []
        if isinstance(sols, str):
            sols = [sols]
        departure = bool(pm.get("departure"))
        watch = bool(pm.get("watch"))
        assignee = (d.get("assignee") or {}).get("name") or "(без ответственного)"
        cid = d.get("company_id")
        company = company_names.get(int(cid), f"company_id={cid}") if cid is not None else "(без компании)"
        created = parse_dt(d.get("created_at"))
        completed = parse_dt(d.get("completed_at"))
        dur_h = None
        if created and completed:
            dur_h = max((completed - created).total_seconds() / 3600.0, 0.0)
            durations_h.append(dur_h)

        by_assignee_count[assignee] += 1
        by_typical_count[typical] += 1
        for s in sols:
            by_solution[s] += 1
        if departure:
            departure_n += 1
        if watch:
            watch_n += 1

        if score is None:
            weight_missing += 1
        else:
            score_dist[score] += 1
            by_assignee_scores[assignee].append(score)
            by_typical_scores[typical].append(score)
            by_company_scores[company].append(score)
            by_company_count[company] += 1
            if created:
                month_scores[created.strftime("%Y-%m")][assignee] += score
            if dur_h is not None and score >= 30 and dur_h < 0.25:
                high_score_short.append(
                    {
                        "id": d.get("id"),
                        "score": score,
                        "hours": round(dur_h, 3),
                        "typical": typical,
                        "assignee": assignee,
                        "title": d.get("title"),
                    }
                )

        assignee_company[assignee][company] += 1

        flat_rows.append(
            {
                "id": d.get("id"),
                "title": d.get("title"),
                "created_at": d.get("created_at"),
                "completed_at": d.get("completed_at"),
                "duration_hours": None if dur_h is None else round(dur_h, 3),
                "status": (d.get("status") or {}).get("code"),
                "type": (d.get("type") or {}).get("code"),
                "assignee": assignee,
                "assignee_id": (d.get("assignee") or {}).get("id"),
                "author": (d.get("author") or {}).get("name"),
                "author_type": (d.get("author") or {}).get("type"),
                "company_id": d.get("company_id"),
                "company": company,
                "group_id": d.get("group_id"),
                "agreement_id": (d.get("agreement") or {}).get("id"),
                "agreement_title": (d.get("agreement") or {}).get("title"),
                "service_object_id": d.get("service_object_id"),
                "ticket_weight": score,
                "typical": typical,
                "solution_method": sols,
                "departure": departure,
                "watch": watch,
                "pos_type": pm.get("pos_type"),
                "knowledge_base_issue": pm.get("knowledge_base_issue"),
                "spent_time_total": d.get("spent_time_total"),
                "reacted_at": d.get("reacted_at"),
                "deadline_at": d.get("deadline_at"),
            }
        )

    def summarize_scores(mapping: dict[str, list[int]], top: int = 30):
        rows = []
        for k, vals in mapping.items():
            if not vals:
                continue
            rows.append(
                {
                    "key": k,
                    "n": len(vals),
                    "sum": sum(vals),
                    "avg": round(statistics.mean(vals), 2),
                    "median": statistics.median(vals),
                    "p90": sorted(vals)[max(int(len(vals) * 0.9) - 1, 0)],
                }
            )
        rows.sort(key=lambda r: r["sum"], reverse=True)
        return rows[:top]

    # concentration: share of tickets from top company per assignee
    concentration = []
    for a, c in assignee_company.items():
        total = sum(c.values())
        top_company, top_n = c.most_common(1)[0]
        concentration.append(
            {
                "assignee": a,
                "tickets": total,
                "top_company": top_company,
                "top_company_share": round(top_n / total, 3) if total else 0,
                "distinct_companies": len(c),
            }
        )
    concentration.sort(key=lambda r: (-r["top_company_share"], -r["tickets"]))

    summary = {
        "issues": len(details),
        "with_weight": len(details) - weight_missing,
        "without_weight": weight_missing,
        "departure": departure_n,
        "watch": watch_n,
        "score_distribution": dict(sorted(score_dist.items(), key=lambda x: x[0])),
        "duration_hours": {
            "median": round(statistics.median(durations_h), 3) if durations_h else None,
            "mean": round(statistics.mean(durations_h), 3) if durations_h else None,
        },
        "by_assignee": summarize_scores(by_assignee_scores, 50),
        "assignee_ticket_counts": by_assignee_count.most_common(50),
        "by_typical": summarize_scores(by_typical_scores, 50),
        "typical_counts": by_typical_count.most_common(50),
        "solution_counts": by_solution.most_common(50),
        "company_concentration": concentration[:50],
        "high_score_short_sample": sorted(high_score_short, key=lambda x: (-x["score"], x["hours"]))[:50],
    }

    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "issues_flat.jsonl").open("w", encoding="utf-8") as f:
        for row in flat_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # markdown report
    lines = [
        "# Анализ заявок Okdesk (черновик)",
        "",
        f"Заявок в выборке: **{summary['issues']}**",
        f"С баллами: **{summary['with_weight']}**, без баллов: **{summary['without_weight']}**",
        f"С выездом: **{summary['departure']}**, с дежурством: **{summary['watch']}**",
        "",
        "## Распределение баллов",
        "",
        "| Баллы | Кол-во |",
        "|------:|-------:|",
    ]
    for score, n in summary["score_distribution"].items():
        lines.append(f"| {score} | {n} |")

    lines += ["", "## Топ исполнителей по сумме баллов", "", "| Исполнитель | Заявок с баллами | Сумма | Среднее | Медиана |", "|---|---:|---:|---:|---:|"]
    for r in summary["by_assignee"][:20]:
        lines.append(f"| {r['key']} | {r['n']} | {r['sum']} | {r['avg']} | {r['median']} |")

    lines += ["", "## Типовые проблемы × баллы", "", "| Типовая проблема | N | Сумма | Среднее | Медиана |", "|---|---:|---:|---:|---:|"]
    for r in summary["by_typical"]:
        lines.append(f"| {r['key']} | {r['n']} | {r['sum']} | {r['avg']} | {r['median']} |")

    lines += [
        "",
        "## Концентрация по клиентам (признак конвейера)",
        "",
        "| Исполнитель | Заявок | Топ-клиент | Доля | Уник. клиентов |",
        "|---|---:|---|---:|---:|",
    ]
    for r in summary["company_concentration"][:20]:
        lines.append(
            f"| {r['assignee']} | {r['tickets']} | {r['top_company']} | {r['top_company_share']} | {r['distinct_companies']} |"
        )

    lines += ["", "## Высокий балл при коротком времени (<15 мин, балл ≥30)", "", f"Найдено: {len(high_score_short)} (в отчёт — топ 20)", ""]
    for r in summary["high_score_short_sample"][:20]:
        lines.append(f"- #{r['id']} | {r['score']} б. | {r['hours']} ч | {r['assignee']} | {r['typical']} | {r['title']}")

    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'summary.json'}")
    print(f"wrote {OUT / 'report.md'}")
    print(f"wrote {OUT / 'issues_flat.jsonl'} ({len(flat_rows)} rows)")


if __name__ == "__main__":
    main()
