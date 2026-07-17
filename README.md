# DIKSON AI System

Модельно-независимая локальная агентная система для долговременной памяти проектов, Wiki, специализированных агентов, skills, задач и автоматизаций.

Основной интеллектуальный стек: OpenAI / ChatGPT / Codex.

Статус: начальная архитектура.

## Локальная установка

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```
## Memory API

Память проекта хранится в append-only JSONL-журнале и поддерживает типы `fact`, `decision`, `task`, `hypothesis`, `source` и `summary`.

- `POST /projects/{project_id}/memory` — добавить запись;
- `GET /projects/{project_id}/memory` — получить записи с фильтрами `kind`, `tag` и `limit`;
- `GET /projects/{project_id}/memory/{memory_id}` — получить запись по идентификатору.

Запись может содержать теги, идентификаторы источников, связи с другими записями и произвольные метаданные.
