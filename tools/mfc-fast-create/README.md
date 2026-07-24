# MFC fast create

Веб-форма для Артёма: вставить дневной список (UCG URL + короткие строки) → выбрать объект / typical / способ → создать и закрыть заявки в Okdesk.

ТЗ: [`docs/23-mfc-fast-create.md`](../../docs/23-mfc-fast-create.md).

## Запуск

```bash
cd tools/mfc-fast-create
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# токен: корневой .env репо (OKDESK_DOMAIN, OKDESK_API_TOKEN)
uvicorn app:app --reload --port 8787
```

Открыть http://127.0.0.1:8787/

По умолчанию в UI включён **dry-run** (без записи). Снимите галку перед реальной пачкой.

## Env

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `OKDESK_DOMAIN` | из `.env` | `https://avers.okdesk.ru` |
| `OKDESK_API_TOKEN` | из `.env` | только на сервере |
| `MFC_COMPANY_ID` | `9` | MFC |
| `MFC_ASSIGNEE_ID` | `5` | Артём |
| `MFC_STATUS_CODES` | `completed` | коды через запятую, по порядку; комментарий на первом |
| `MFC_DRY_RUN` | off | если `1` — batch всегда dry-run |
| `INTRASERVICE_HOST` | `help.ucg.ru` | хост IntraService |
| `INTRASERVICE_USER` / `INTRASERVICE_PASSWORD` | — | Basic auth для подтяжки Name/Description |
| `INTRASERVICE_BASIC` | — | готовый Base64 (`user:pass`) вместо пары логин/пароль |

Без учётки IntraService ссылки **парсятся** (`/Task/View/{id}` → id + URL), но title остаётся `UCG #id`. С учёткой в UI появляется галка «подтянуть title из IntraService».

## API

- `GET /api/mfc/catalogs`
- `GET /api/mfc/objects?q=`
- `POST /api/mfc/parse` — `{ "text": "…" }`
- `POST /api/mfc/batch` — create + status(es)
- `POST /api/mfc/objects/refresh`

## Тесты

```bash
pytest tests/ -q
```

Поля N / осложнение: коды `object_count`, `complication_level` (`+15`/`+30`), `complication` (описание). Без пары уровень+текст batch отклоняет строку. `ticket_weight` по-прежнему не ставим.


## Prod (git.averstech.ru)

Деплой контейнера — в репо `gitlab-avers` (`mfc-fast-create` + location `/mfc/` в GitLab nginx).

API: `https://git.averstech.ru/mfc/`  
UI: ShiftPlanner GitHub Pages `mfc-tool.html`.
