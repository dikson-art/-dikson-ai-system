# Documentation Generator

Documentation Generator формирует проверяемые Markdown-артефакты из текущих runtime-контрактов системы.

## Архитектура

- `dikson_li.documentation` — чистый renderer, модели snapshot и append-only JSONL repository;
- `app.documentation_service` — OpenAPI/Agent Registry orchestration и создание Documentation Agent proposal;
- `app.documentation_api` — HTTP adapter;
- `data/projects/{project_id}/documentation/snapshots.jsonl` — immutable snapshots.

Генерируются `generated/api-reference.md` и `generated/agent-catalog.md`. Контент хранится вместе с SHA-256, а `source_digest` вычисляется из канонически сериализованных OpenAPI и manifests.

## Workflow

```text
FastAPI OpenAPI + Agent Registry
              ↓
   Documentation Generator
              ↓
 immutable Markdown snapshot
              ↓
pending Documentation Agent proposal
              ↓
       human review / decision
```

Генератор намеренно не записывает файлы в репозиторий и не обновляет Wiki. После review отдельный Coding/Git workflow сможет применить выбранные артефакты без обхода approval boundary.

## API

- `POST /projects/{project_id}/documentation/snapshots`;
- `GET /projects/{project_id}/documentation/snapshots`;
- `GET /projects/{project_id}/documentation/snapshots/{snapshot_id}`.

`idempotency_key` закрепляет snapshot независимо от повторного запроса. Без ключа идентичный source digest создаёт тот же snapshot.
