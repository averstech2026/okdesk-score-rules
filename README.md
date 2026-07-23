# Okdesk Score Rules

Правила оценки заявок и формирования премии инженеров (Okdesk): нормативные баллы, выезды, дежурства, потоки работ и контур контроля.

## Зачем

Текущая практика (инженер сам ставит баллы «на глаз») даёт разночтения и слабый контроль при ~1000 заявок/мес. Цель ревизии:

1. Сохранить привычную модель **баллов**, но убрать свободную самооценку.
2. Учесть разные режимы труда: **конвейер** (типовые контракты) vs **общий пул**.
3. Отделить ответственность **человека** от ответственности **очереди** (SLA).
4. Подготовить основу для аналитики аномалий (приписки, перекос в «лёгкий» поток).

## Документы

| Файл | Содержание |
|------|------------|
| [docs/00-principles.md](docs/00-principles.md) | Принципы и границы системы |
| [docs/01-base-catalog.md](docs/01-base-catalog.md) | Справочник: тип работ → базовые баллы |
| [docs/02-complications.md](docs/02-complications.md) | Надбавки за осложнение |
| [docs/03-field-visits.md](docs/03-field-visits.md) | Выезды (фикс по зоне) |
| [docs/04-duty.md](docs/04-duty.md) | Дежурства (×2) |
| [docs/05-streams.md](docs/05-streams.md) | Потоки: конвейер vs общий пул |
| [docs/06-sla.md](docs/06-sla.md) | SLA: группа vs исполнитель |
| [docs/07-bonus.md](docs/07-bonus.md) | Формула премии (черновик) |
| [docs/08-audit.md](docs/08-audit.md) | Аудит и флаги аномалий |
| [docs/09-data-findings.md](docs/09-data-findings.md) | Находки по реальной выгрузке Okdesk |
| [docs/10-typical-catalog-proposal.md](docs/10-typical-catalog-proposal.md) | Ревизия справочника типовых проблем |
| [docs/11-ticket-contours.md](docs/11-ticket-contours.md) | Контуры заявок: нативные / MFC-перенос / почта-чаты |
| [docs/12-nonstandard-issue-type.md](docs/12-nonstandard-issue-type.md) | Тип «Нестандарт» вместо «Другое» (без Expert) |
| [docs/13-solution-catalog-proposal.md](docs/13-solution-catalog-proposal.md) | Ревизия справочника способов решения |
| [docs/14-handoff.md](docs/14-handoff.md) | Как продолжить без истории чата |
| [docs/15-balance-conveyor-vs-investigations.md](docs/15-balance-conveyor-vs-investigations.md) | Баланс конвейер vs расследования, анти-перехват |
| [docs/16-handoff-internal-app.md](docs/16-handoff-internal-app.md) | **Передача в соседний проект:** личные отчёты премии/дежурств, массовые заявки, accept |
| [docs/17-implementation-plan.md](docs/17-implementation-plan.md) | **Пошаговый план внедрения** нового подхода (фазы 0–6) |
| [docs/18-phase0-decisions.md](docs/18-phase0-decisions.md) | **Фаза 0:** лист решений (в т.ч. текст «Осложнение») |
| [docs/19-phase0-revision.md](docs/19-phase0-revision.md) | **Фаза 0:** было → станет (markdown) |
| [docs/20-phase0-comment-answers.md](docs/20-phase0-comment-answers.md) | Ответы на комментарии к HTML фазы 0 |
| [docs/21-okdesk-new-fields.md](docs/21-okdesk-new-fields.md) | **Финал:** новые поля Okdesk |
| [docs/22-typical-base-weights.md](docs/22-typical-base-weights.md) | **Typical → база баллов** (+ статьи БЗ) |
| [docs/23-mfc-fast-create.md](docs/23-mfc-fast-create.md) | **MFC:** быстрая форма create+close (Артём; объекты; парсер URL/текста) |
| [analysis/phase0-revision.html](analysis/phase0-revision.html) | **HTML:** фаза 0 было → станет (для согласования) |
| [docs/open-questions.md](docs/open-questions.md) | Открытые вопросы для согласования |
| [analysis/report.md](analysis/report.md) | Сводный отчёт по последней выгрузке |
| [analysis/bonus-comparison.md](analysis/bonus-comparison.md) | **Сравнение премий:** факт vs новый подход (по сотрудникам и месяцам, 1 балл = 15 ₽) |
| [analysis/bonus-comparison.html](analysis/bonus-comparison.html) | **HTML:** помесячное сравнение текущий / новый по каждому инженеру |
| [analysis/mass-update-auto.html](analysis/mass-update-auto.html) | **Массовые обновления ПО:** объём, премия, сценарии автообновления |
| [analysis/typical-catalog.html](analysis/typical-catalog.html) | **HTML-сводка для передачи:** план, данные, каталоги |

## Статус

Черновик v0 — зафиксированы договорённости из обсуждения. Числа в каталоге и формула премии требуют наполнения/утверждения.

## Репозиторий

https://github.com/averstech2026/okdesk-score-rules
