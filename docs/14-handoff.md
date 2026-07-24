# Передача работы (handoff)

История чата Cursor на другой компьютер **не переносится**.

**Снимок контекста (2026-07-24 вечер):** фаза 0 согласована → **фаза 1** в Okdesk. MFC fast create **задеплоен на прод**. Полный снимок всех треков: **[docs/26-session-continue-2026-07-24.md](26-session-continue-2026-07-24.md)**.

## С чего начать на новом ПК

1. `git clone` / `git pull` → https://github.com/averstech2026/okdesk-score-rules  
2. Открыть **[analysis/typical-final.html](../analysis/typical-final.html)** (typical) и **[analysis/solution-final.html](../analysis/solution-final.html)** (способы).  
3. Поля: [docs/21-okdesk-new-fields.md](21-okdesk-new-fields.md).  
4. В Cursor: workspace = папка репо.

### Два трека

| Трек | С чего | Промпт |
|------|--------|--------|
| **Фаза 1 Okdesk** | docs/21, 22, 25 · typical-final / solution-final | «заводим каталоги и поля в Okdesk по docs/21–22–25» |
| MFC fast create (**прод**) | [docs/23](23-mfc-fast-create.md) · [docs/26](26-session-continue-2026-07-24.md) | «продолжи MFC по docs/26» |

---

## Где мы (2026-07-24)

**Фаза 0** — каталоги и правила **утверждены**. **Фаза 1** — создать в Okdesk (ещё не сделано вручную).

### Правила (формула)

```
выезд → только 60 × (1|2)
Нестандарт → (15 + осложнение*) × (1|2)   // typical на форме нет
иначе → (база(typical) × N + осложнение*) × (1|2)
```

Базы: **T5=5 · C15=15 · S30=30 · H60=60**. Префиксы веса в именах typical **пока не ставим**.

### Typical — 22 пункта

Канон: [docs/22](22-typical-base-weights.md) · HTML: [typical-final.html](../analysis/typical-final.html).  
Без «Другое»; сопутствующие сервисы → Нестандарт + Суть.

### Способы — 19 пунктов

Канон: [docs/25](25-solution-final.md) · HTML: [solution-final.html](../analysis/solution-final.html).  
Без «Другое»/«Бумага»; матрица typical→способ; +№19 «Статья БЗ».

### Свойства Okdesk

[docs/21](21-okdesk-new-fields.md): осложнение (+15/+30) + описание; N; тип Нестандарт + Суть.  
На Нестандарте: **typical скрыть**, обязательны Суть + способ. Причина выезда — **не** заводим.

### Отложено

§0.5–0.6 (сегменты / целевые на расследования) — не блокируют фазу 1.  
Коммуникация команде — перед/вместе с фазой 1.

---

## Пайплайн (кратко)

Полный план: [17](17-implementation-plan.md). Лист фазы 0: [18](18-phase0-decisions.md).

| # | Шаг | Статус |
|---|-----|--------|
| 1 | Контуры / KPI без MFC | ок |
| 2 | Typical 22 | **утв.** |
| 3 | Нестандарт (без typical на форме) | **утв.** |
| 4 | Solution 19 + матрица | **утв.** |
| 5 | Баланс конвейер vs расследования | отложено (docs/15) |
| 6 | Нормы / формула | **утв.** |
| → | **Фаза 1:** завести в Okdesk | **следующее** |

---

## Карта файлов

| Файл | Зачем |
|------|--------|
| [typical-final.html](../analysis/typical-final.html) | Имена typical + покрытие |
| [solution-final.html](../analysis/solution-final.html) | Способы + матрица |
| [docs/21](21-okdesk-new-fields.md) | Новые поля / Нестандарт |
| [docs/22](22-typical-base-weights.md) | Typical → база |
| [docs/25](25-solution-final.md) | Способы |
| [docs/12](12-nonstandard-issue-type.md) | Нестандарт: typical off |
| [docs/00](00-principles.md) · [01](01-base-catalog.md) | Принципы / коды баз |
| [docs/17](17-implementation-plan.md) · [18](18-phase0-decisions.md) | План / чеклист фазы 0 |
| [docs/23](23-mfc-fast-create.md) · `tools/mfc-fast-create/` | MFC-трек |
| `scripts/*` | Выгрузка / симуляции / coverage |

## Ограничения тарифа Okdesk

Ниже Expert 50+: без автоправил. Нестандарт = тип + привязка атрибутов к типу; typical снять с типа вручную в настройках атрибута.
