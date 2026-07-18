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
