# DIKSON AI System

Модельно-независимая локальная AI-система для долговременной памяти проектов, Wiki, исследований, специализированных агентов, задач и автоматизаций.

Основной интеллектуальный стек: OpenAI / ChatGPT / Codex.

Статус: Memory, Wiki, Knowledge Graph, Semantic Search, Agent Framework, Task Queue, Planning System, Research Engine, Git Automation и Documentation Generator объединены в FastAPI MVP.

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

## Semantic Search API

Единый endpoint ищет по Memory, Wiki, Source chunks и явным Knowledge Graph entities. Поисковая проекция строится из канонических хранилищ и не создаёт вторую копию знаний.

- `GET /projects/{project_id}/search?q=...` — гибридный vector search;
- `entity_type` — фильтр `memory`, `wiki_page`, `source`, `graph_node`;
- `limit`, `min_score` — управление выдачей;
- `include_archived=true` — включить архивные Wiki pages.

Локальный backend включён по умолчанию и не требует сети. Для OpenAI embeddings задайте `SEARCH_EMBEDDING_PROVIDER=openai`, `OPENAI_API_KEY` и при необходимости `OPENAI_EMBEDDING_MODEL` (по умолчанию `text-embedding-3-small`). Существующий JSON-контейнер `results` и source-поля `source_id`, `filename`, `chunk` сохранены.

## Agent Framework API

Встроенный registry содержит Research, Planning, Memory, Wiki, Coding, Review и Documentation agents. У каждой роли есть собственные responsibilities, allowlist tools, допустимые proposal types и персональное представление памяти.

- `GET /agents` — реестр ролей;
- `POST /projects/{project_id}/agents/{agent_id}/runs` — зарегистрировать запуск с проверкой tools;
- `POST /projects/{project_id}/agents/{agent_id}/runs/{run_id}/proposals` — сохранить предложение;
- `GET /projects/{project_id}/agents/proposals` — получить предложения и решения;
- `POST /projects/{project_id}/agents/proposals/{proposal_id}/decisions` — подтвердить или отклонить;
- `POST /projects/{project_id}/agents/proposals/{proposal_id}/commit-memory` — сохранить подтверждённую agent memory;
- `GET /projects/{project_id}/agents/{agent_id}/memory` — память конкретной роли.

Agents не меняют доменные данные напрямую. Runs, proposals и decisions хранятся append-only; подтверждённая память проходит через единственный `JsonlMemoryStore`.

## Task Queue API

Durable очередь принимает только существующие Agent Runs и хранит неизменяемые tasks вместе с append-only lifecycle events. Workers используют атомарные leases, heartbeat, retries и dead-letter.

- `POST /projects/{project_id}/tasks` — добавить run в очередь;
- `POST /projects/{project_id}/tasks/claim` — получить следующую задачу и lease token;
- `GET /projects/{project_id}/tasks` — список и фильтр status;
- `GET /projects/{project_id}/tasks/{task_id}/events` — audit history;
- `POST .../heartbeat`, `.../complete`, `.../fail`, `.../cancel` — безопасные переходы состояния.

Claim учитывает priority и delayed `available_at`. `idempotency_key` предотвращает повторный enqueue, а lease token никогда не возвращается из list/get/events API.

## Planning System API

План представляет собой проверенный ациклический граф шагов. Каждый шаг закреплён за встроенной ролью агента, проходит deny-by-default проверку tools и попадает в Task Queue только после подтверждения и активации всего плана.

- `POST /projects/{project_id}/plans` — создать draft-план;
- `GET /projects/{project_id}/plans` — получить планы с необязательным фильтром `status`;
- `GET /projects/{project_id}/plans/{plan_id}` — получить вычисленное состояние DAG;
- `POST .../decision` — подтвердить или отклонить draft;
- `POST .../activate` — активировать подтверждённый план;
- `POST .../dispatch` — идемпотентно отправить готовые шаги в Agent Framework и Task Queue;
- `POST .../cancel` — остановить будущую диспетчеризацию плана.

Зависимый шаг становится `ready` только после успешного завершения всех предшественников. Ошибка, dead-letter или отмена шага переводят активный план в `blocked`; успех всех шагов — в `completed`. Подробности: [docs/PLANNING_SYSTEM.md](docs/PLANNING_SYSTEM.md).

## Research Engine API

Research Study хранит проверяемый вопрос, дополнительные поисковые запросы, snapshot доказательств со стабильными citations и итоговый отчёт. При создании автоматически формируется draft DAG `gather-evidence → synthesize-report`; выполнение начинается только после approve и activate.

- `POST /projects/{project_id}/research` — совместимый быстрый ответ без создания study;
- `POST /projects/{project_id}/research/studies` — создать идемпотентное исследование и draft plan;
- `GET /projects/{project_id}/research/studies` — список исследований;
- `GET /projects/{project_id}/research/studies/{study_id}` — study, plan, evidence и report;
- `POST .../decision` и `.../activate` — human approval исследовательского плана;
- `POST .../advance` — выполнить готовые research tasks через атомарные leases.

Без `OPENAI_API_KEY` evidence collection и весь workflow работают локально, а отчёт явно сообщает об отсутствии model synthesis. При наличии ключа используется stateless OpenAI Responses API. Итог сохраняется как pending `research_report` proposal и не изменяет Memory/Wiki без отдельного human decision. Подробности: [docs/RESEARCH_ENGINE.md](docs/RESEARCH_ENGINE.md).

## Git Automation API

Git Automation читает status/diff и превращает только подтверждённый `code_change` proposal Coding Agent в новую локальную ветку `agent/*` с одним коммитом. Произвольные команды, hooks, push, merge и изменение `main` не поддерживаются.

- `GET /projects/{project_id}/git/status` — безопасный machine-readable status;
- `GET /projects/{project_id}/git/diff?staged=false` — ограниченный текстовый diff;
- `GET /projects/{project_id}/git/executions` — append-only журнал выполнений;
- `POST /projects/{project_id}/git/proposals/{proposal_id}/execute` — применить одобренный патч в изолированном worktree.

Репозиторий проекта находится в `GIT_REPOSITORIES_DIR/{project_id}` (по умолчанию `repositories/{project_id}`). Proposal задаёт `branch`, `commit_message`, unified `patch`, необязательные `base_ref` и `expected_head`. Подробности: [docs/GIT_AUTOMATION.md](docs/GIT_AUTOMATION.md).

## Documentation Generator API

Генератор детерминированно строит Markdown API Reference из текущего FastAPI OpenAPI и Agent Catalog из канонического Agent Registry. Результат сохраняется immutable snapshot и создаёт pending proposal Documentation Agent; README/Wiki автоматически не изменяются.

- `POST /projects/{project_id}/documentation/snapshots` — создать идемпотентный snapshot;
- `GET /projects/{project_id}/documentation/snapshots` — получить историю генераций;
- `GET /projects/{project_id}/documentation/snapshots/{snapshot_id}` — получить артефакты и proposal ID.

Подробности: [docs/DOCUMENTATION_GENERATOR.md](docs/DOCUMENTATION_GENERATOR.md).
