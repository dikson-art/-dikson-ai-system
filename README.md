# DIKSON AI System

Модельно-независимая локальная AI-система для долговременной памяти проектов, Wiki, исследований, специализированных агентов, задач и автоматизаций.

Основной интеллектуальный стек: OpenAI / ChatGPT / Codex.

Статус: единое ядро памяти и FastAPI MVP.

## Локальная установка

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## Memory API

FastAPI и CLI используют одно каноническое ядро `dikson_li.memory.JsonlMemoryStore`. Записи хранятся в UTF-8 JSONL по пути `data/projects/{project_id}/memory.jsonl`.

Поддерживаемые типы: `fact`, `decision`, `task`, `hypothesis`, `source`, `summary`.

- `POST /projects/{project_id}/memory` — добавить запись;
- `GET /projects/{project_id}/memory` — последние записи с фильтрами `kind`, `tag`, `source_id`, `limit`;
- `GET /projects/{project_id}/memory/{memory_id}` — запись по ID.

Каноническое поле — `content`; старое входное поле `text` продолжает приниматься. Старые CLI-журналы из `data/memory/*.jsonl` мигрируют при первом чтении.

## CLI

```powershell
dikson-li remember my-project "Подтверждённый факт" --kind fact
dikson-li recall my-project --limit 20
```

Путь данных задаётся переменной `DIKSON_DATA_DIR` и одинаков для CLI и API.
## Wiki API

Wiki хранит страницы как Markdown с валидируемым YAML front matter в `data/projects/{project_id}/wiki/pages`. Обновления и архивирование создают immutable history snapshots; физическое удаление endpoint не выполняет.

- `POST /projects/{project_id}/wiki/pages` — создать страницу;
- `GET /projects/{project_id}/wiki/pages` — список и поиск по `q`, `tag`, `include_archived`;
- `GET /projects/{project_id}/wiki/pages/{page_id}` — страница и backlinks;
- `PUT /projects/{project_id}/wiki/pages/{page_id}` — обновить с actor/reason;
- `DELETE /projects/{project_id}/wiki/pages/{page_id}` — безопасно архивировать;
- `GET /projects/{project_id}/wiki/pages/{page_id}/history` — история изменений.

Wiki связывается с памятью через `related_memory_ids`; Memory Core предусматривает обратные `related_page_ids`. Автоматического продвижения гипотез в подтверждённые Wiki-факты нет.

## Knowledge Graph API

Knowledge Graph строит живую проекцию Memory, Wiki и загруженных документов по стабильным ID. People, Articles, Research и другие внешние сущности сохраняются отдельно в append-only JSONL, поэтому граф не копирует доменные данные.

- `GET /projects/{project_id}/graph` — snapshot с фильтрами `node_type`, `edge_type`, `q`;
- `POST /projects/{project_id}/graph/nodes` — добавить внешнюю сущность;
- `POST /projects/{project_id}/graph/edges` — добавить типизированную связь;
- `GET /projects/{project_id}/graph/nodes/{node_id}/neighbors` — ближайшее окружение узла.

Проекционные узлы используют ID `project:*`, `memory:*`, `wiki:*`, `source:*`. Явные graph nodes/edges хранятся в `data/projects/{project_id}/graph/*.jsonl`.
