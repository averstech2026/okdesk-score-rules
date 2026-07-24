# Снимок сессий — продолжить с любого ПК (2026-07-24)

История Cursor **не переносится**. После `git pull` откройте этот файл.

Связанные репо:  
[okdesk-score-rules](https://github.com/averstech2026/okdesk-score-rules) ·  
[ShiftPlanner](https://github.com/averstech2026/ShiftPlanner) ·  
[gitlab-avers](https://github.com/averstech2026/gitlab-avers)

---

## Три активных трека

| # | Трек | Статус | Следующий шаг | Канон |
|---|------|--------|---------------|--------|
| A | **Баллы / каталоги Okdesk** | Фаза 0 **утверждена** | **Фаза 1:** завести typical/solution/поля в Okdesk | [14-handoff](14-handoff.md), [21](21-okdesk-new-fields.md), [22](22-typical-base-weights.md), [25](25-solution-final.md) |
| B | **MFC fast create** | **На проде** | Прогон живых заявок Артёмом; при необходимости UX/безопасность API | [23-mfc-fast-create](23-mfc-fast-create.md) + § ниже |
| C | **ShiftPlanner отчёты/дежурства** | MVP отсечки в коде | Дни 200/400 из табеля; кабинет не-админа; маппинг email↔Okdesk | ShiftPlanner `docs/20-session-handoff-okdesk-issues.md` |

Отложено / не блокирует: сегменты KPI (docs/15), миграция Firestore→Postgres (ShiftPlanner `docs/21-firestore-oss-migration-notes.md`), Firebase Blaze.

---

## Трек B — MFC (актуально после деплоя)

### Как пользоваться

| Что | URL |
|-----|-----|
| UI (GitHub Pages) | https://averstech2026.github.io/ShiftPlanner/mfc-tool.html |
| API health | https://git.averstech.ru/mfc/api/mfc/health |
| Доступ UI | Firebase Auth + allowlist: `i.merkulov@averstech.ru`, `inert@mail.ru`, `nadya@averstech.ru` |

Архитектура: **UI на GH Pages** → `fetch` → **FastAPI** на VPS (`git.averstech.ru/mfc/`, nginx GitLab → контейнер `mfc-fast-create`).  
Firebase Functions `mfcApi` **не используем** (Spark, без Blaze).

### Код

| Место | Назначение |
|-------|------------|
| `okdesk-score-rules/tools/mfc-fast-create/` | Канон FastAPI + static (локальная разработка) |
| `gitlab-avers/mfc-fast-create/` | Копия для Docker на `/opt/gitlab` |
| `ShiftPlanner/mfc-tool.html` + `mfc-tool/` + `js/mfc-*.js` | Прод UI; `MFC_API_BASE = https://git.averstech.ru/mfc` |

### Сервер

- Host: `170.168.10.152` · путь `/opt/gitlab`
- Сервисы: `gitlab`, `mfc-fast-create`, `docs`, `planka-bridge`
- Секреты: `/opt/gitlab/mfc-fast-create/.env` (не в git)
- Обновление:
  ```bash
  cd /opt/gitlab
  # скопировать код / git pull зеркала, затем:
  docker compose up -d --build mfc-fast-create
  # nginx /mfc/ — в GITLAB_OMNIBUS_CONFIG; при смене compose:
  docker compose up -d gitlab   # долгий reconfigure
  ```

### Известные решения при деплое

- В Docker `REPO_ROOT = ROOT` если нет parents (иначе IndexError).
- В `docker-compose` для nginx: `$$host` / `$$remote_addr` (иначе compose съедает `$`).
- CORS: `MFC_CORS_ORIGINS` включает `https://averstech2026.github.io`.

### Промпт для продолжения

> Продолжи MFC fast create: прод на git.averstech.ru/mfc, UI в ShiftPlanner mfc-tool.html. Контекст docs/23 и docs/26.

---

## Трек A — фаза 1 Okdesk

Промпт: «заводим каталоги и поля в Okdesk по docs/21–22–25 и 14-handoff».

HTML: `analysis/typical-final.html`, `analysis/solution-final.html`.

---

## Трек C — ShiftPlanner

Промпт: «продолжи по docs/20 — duty settlements / кабинет / дни 200×400».

Дополнительно: Planka↔GitLab bridge живёт в `gitlab-avers` (`planka-bridge`), доска board.averstech.ru.

---

## Чаты Cursor (ориентиры, не переносятся)

| Тема | Проект / id (фрагмент) |
|------|-------------------------|
| Вес + MFC → прод | okdesk-score-rules `12034a51…` |
| Фаза 0 каталоги | okdesk-score-rules `9e0c8b7a…` |
| Okdesk issues / duty | ShiftPlanner `343122b1…`, `docs/20` |
| Firestore миграция (идеи) | ShiftPlanner `db618ade…`, `docs/21` |
| Planka↔GitLab | gitlab-avers `0af1d088…` |

---

## Не коммитить

`.env`, пароли сервера, `data/`, ключи SA.
