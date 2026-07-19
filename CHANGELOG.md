# Changelog

Все заметные изменения проекта документируются в этом файле.

## Unreleased

### Added

- Добавлен Planning System с валидируемыми DAG, approval/activation lifecycle и вычисляемыми состояниями шагов.
- Добавлена policy-проверка agent tools и идемпотентная диспетчеризация ready-шагов в Agent Framework и Task Queue.
- Добавлены append-only plan/event streams, project orchestration lock и восстановление dispatch после частичного сбоя.
- Добавлены core/service/API тесты циклов, зависимостей вне порядка, policy denial, lifecycle, повторного dispatch, завершения и corruption safety.

### Changed

- Agent Runs получили необязательный `idempotency_key`; существующий API-контракт сохранён.

### Added

- Добавлена durable Task Queue, связанная только с policy-validated Agent Runs.
- Добавлены priority, delayed availability, project idempotency, atomic leases, heartbeat, retries, cancellation и dead-letter.
- Добавлены append-only task/event streams, lease reclamation и публичные API-модели без утечки lease token.
- Добавлены core/API тесты concurrency claim, stale token, retry delay, lease expiry, terminal failures и corruption safety.

### Added

- Добавлен Agent Framework с семью встроенными ролями: Research, Planning, Memory, Wiki, Coding, Review и Documentation.
- Добавлены deny-by-default tool policy, типизированные runs/proposals/decisions и append-only audit repository.
- Добавлена подтверждаемая и идемпотентная agent memory через канонический Memory Core без второго хранилища памяти.
- Добавлены Agent Registry/API endpoints и тесты policy isolation, corruption safety, single-decision и approval workflow.

### Changed

- `AGENT_PROTOCOL` расширен manifests, proposal lifecycle, human confirmation и границей будущей Task Queue.

### Added

- Добавлен единый Semantic Search по Memory, Wiki, Source chunks и явным Knowledge Graph entities.
- Добавлены provider-neutral `EmbeddingModel`, автономный multilingual local backend и опциональный OpenAI Embeddings adapter.
- Добавлены cosine ranking, морфологические признаки, graph context boost, фильтры типа/score/archive и безопасные ошибки API.
- Добавлены core/service/API тесты ранжирования, всех источников, совместимости source results, OpenAI batch contract и повреждённых данных.

### Changed

- `/projects/{project_id}/search` и Research Engine используют единый поисковый сервис; старый source search оставлен только как совместимый адаптер.

### Added

- Добавлен Knowledge Graph с автоматической проекцией Projects, Memory, Tasks, Wiki Pages и Documents.
- Добавлены явные People, Articles, Research и другие graph entities, типизированные edges, фильтры и neighbors API.
- Добавлено append-only JSONL-хранилище графа с `FileLock`, corruption detection и безопасными HTTP-ошибками.
- Добавлены core/API тесты проекции Memory↔Wiki↔Sources, Unicode, duplicate entities и повреждённого graph storage.
### Added

- Добавлен Wiki CRUD на Markdown + YAML front matter с поиском, backlinks, source/memory/page links и защитой duplicate slug.
- Добавлена immutable история create/update/archive с actor, reason, operation ID и предыдущей версией.
- Добавлены soft archive и атомарная запись Wiki-файлов без физического удаления.
- Добавлены Wiki Core и API-тесты для русского текста, истории, поиска, backlinks и безопасных ошибок.
### Added

- Добавлено единое типизированное Memory Core для FastAPI и CLI с фильтрами, связями, Unicode и безопасной межпроцессной записью.
- Добавлена одноразовая миграция старых CLI JSONL-журналов с детерминированными ID.
- Добавлены сквозные и отказоустойчивые тесты API, CLI и core.

### Changed

- CLI и FastAPI теперь используют общий `DIKSON_DATA_DIR` и канонический путь `data/projects/{project_id}/memory.jsonl`.

### Fixed

- Исправлена editable- и wheel-установка: setuptools теперь явно собирает пакеты `app` и `dikson_li`, не принимая каталоги данных за Python-пакеты.
