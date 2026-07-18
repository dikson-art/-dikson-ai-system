# Agent Framework

## Назначение

Agent Framework задаёт стабильный контракт для независимых AI-ролей до подключения конкретной модели или очереди задач. Он отделяет identity и policy от исполнения и сохраняет полный audit trail.

## Слои

```text
FastAPI Agent Router
        ↓
Agent Framework Service
   ├─ Agent Registry / Tool Policy
   ├─ Run + Proposal + Decision Audit
   └─ Approved Agent Memory Adapter
                    ↓
          Canonical Memory Core
```

- `dikson_li.agents` — canonical models, built-in registry, authorization rules и append-only JSONL repository;
- `app.agent_service` — project scope, proposal validation и интеграция с Memory Core;
- `app.agent_api` — HTTP adapter и безопасное преобразование ошибок.

## Встроенный реестр

Реестр содержит ровно семь ролей: Research, Planning, Memory, Wiki, Coding, Review и Documentation. Manifest каждой роли содержит responsibilities, allowlist tools, допустимые proposal types и уникальный memory tag.

Реестр является кодовым контрактом Agent Framework. Runtime-регистрация произвольных агентов намеренно не поддерживается: до появления подписанных manifests и migration policy она ослабила бы безопасность allowlist.

## Хранение

`data/projects/{project_id}/agents` содержит:

- `runs.jsonl` — принятые запуски и requested tools;
- `proposals.jsonl` — предложения агентов;
- `decisions.jsonl` — однократные human decisions.

Файлы append-only, защищены project-scoped `FileLock`, `flush` и `fsync`. Повреждённая непустая строка вызывает `AgentCorruptionError`; API не раскрывает путь или номер строки.

Журнал агентов хранит процесс и аудит, но не копирует знания. Подтверждённая персональная память записывается в `memory.jsonl` через единственный `JsonlMemoryStore` и отличается тегом `agent:*` и metadata с proposal/reviewer IDs.

## API

- `GET /agents` — manifests всех ролей;
- `GET /agents/{agent_id}` — manifest роли;
- `POST /projects/{project_id}/agents/{agent_id}/runs` — принять запуск после tool policy;
- `GET /projects/{project_id}/agents/runs` — журнал запусков;
- `POST /projects/{project_id}/agents/{agent_id}/runs/{run_id}/proposals` — добавить предложение;
- `GET /projects/{project_id}/agents/proposals` — предложения с вычисленным статусом;
- `POST /projects/{project_id}/agents/proposals/{proposal_id}/decisions` — approve/reject;
- `POST /projects/{project_id}/agents/proposals/{proposal_id}/commit-memory` — идемпотентно сохранить подтверждённую agent memory;
- `GET /projects/{project_id}/agents/{agent_id}/memory` — изолированное представление памяти роли.

## Инварианты

- неизвестный tool или proposal type отклоняется до изменения состояния;
- proposal не изменяется после записи;
- для proposal допустимо только одно решение;
- неподтверждённая память не коммитится;
- повторный commit возвращает ту же Memory record;
- Agent Framework не исполняет shell, Git или сетевые операции самостоятельно.

## Выполнение

Task Queue принимает только существующие Agent Runs и добавляет durable delivery, leases, retries и audit events. Agent Framework остаётся источником identity и tool policy; очередь не расширяет разрешения роли.
