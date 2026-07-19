# Research Engine

## Назначение

Research Engine превращает вопрос в проверяемое исследование: draft plan, evidence snapshot, cited report и pending Agent Proposal. Он переиспользует существующие Planning System, Agent Framework, Task Queue, Semantic Search и Knowledge Graph вместо создания параллельных реализаций.

## Слои и данные

- `dikson_li.research` — модели studies/evidence/reports, дедупликация и append-only repository;
- `app.research_service` — orchestration, synthesis port и интеграция доменных сервисов;
- `app.research_api` — совместимый quick endpoint и project-scoped Study API.

Данные находятся в `data/projects/{project_id}/research`:

- `studies.jsonl` — неизменяемые вопросы и параметры поиска;
- `events.jsonl` — plan link, evidence snapshot и completed report;
- `.research.lock` — repository serialization;
- `.orchestration.lock` — сериализация create/advance между процессами.

Evidence сохраняется намеренно: отчёт должен оставаться воспроизводимым и проверяемым, даже если канонический Memory/Wiki/Source позднее изменится. Execution status не сохраняется второй раз и всегда читается из Planning/Task Queue.

## Workflow

```text
create Study
    ↓
draft plan: gather-evidence → synthesize-report
    ↓ human approve + activate
dispatch exact ready task
    ↓
Semantic Search(question + queries)
    ↓ max score per document, stable order
Evidence E1..En
    ↓
local/OpenAI synthesis
    ↓
idempotent research_report proposal → pending human decision
```

Шаг `gather-evidence` разрешает Research Agent только `semantic_search`, `graph_read`, `source_read` и `memory_read`. Шаг отчёта не расширяет tool allowlist. Engine получает lease по конкретному `task_id`, поэтому не перехватывает постороннюю research-задачу из общей очереди.

## Надёжность

- `idempotency_key` study предотвращает повторное создание исследования;
- `research_study_id` в plan metadata позволяет восстановить связь после частичного сбоя;
- Planning System идемпотентно восстанавливает Agent Run и Queue Task;
- report proposal использует ключ `research:{study_id}:report`;
- evidence и report events записываются не более одного раза;
- повторный `advance` completed study возвращает существующий результат;
- JSONL append использует `FileLock`, `flush` и `fsync`.

Provider failure переводит текущую задачу обратно в retry lifecycle Task Queue. Corrupt storage возвращает безопасный HTTP 500 без раскрытия содержимого строки.

## Synthesis adapters

По умолчанию система полностью локальна. Если evidence нет, отчёт явно фиксирует пробел. Если evidence найден, но `OPENAI_API_KEY` отсутствует, пользователь получает источники и прозрачное сообщение, что model synthesis отключён.

При наличии ключа `OpenAIResearchSynthesizer` вызывает официальный Responses API через `client.responses.create`, передаёт guidance в `instructions`, материалы в `input`, читает `response.output_text` и устанавливает `store=False`. Модель задаётся существующим `OPENAI_MODEL`; Research Core от конкретной модели не зависит.

## HTTP API

| Метод | Endpoint | Назначение |
|---|---|---|
| `POST` | `/projects/{project_id}/research` | Быстрый совместимый ответ |
| `POST` | `/projects/{project_id}/research/studies` | Создать Study и draft plan |
| `GET` | `/projects/{project_id}/research/studies` | Список Studies |
| `GET` | `/projects/{project_id}/research/studies/{study_id}` | Полный read model |
| `POST` | `.../{study_id}/decision` | Approve/reject plan |
| `POST` | `.../{study_id}/activate` | Активировать approved plan |
| `POST` | `.../{study_id}/advance` | Выполнить доступные research steps |

Lifecycle violation возвращает 409, недоступный search/model provider — 503, отсутствующий проект или Study — 404.

## Knowledge Graph

Graph projection создаёт узел `research:{study_id}` типа `research`, project `contains` edge и `derived_from` edges к использованным Memory, Wiki и Source entities. Graph хранит только вычисляемую проекцию: источником истины остаётся Research Repository.

## Границы

- Research Engine не подтверждает собственный plan;
- Research Agent не коммитит Memory или Wiki напрямую;
- отчёт требует отдельного решения через Agent Proposal API;
- внешнее web-research и ingestion новых источников не имитируются локальным поиском и могут быть добавлены позднее как отдельные разрешённые adapters;
- следующий слой Git Automation должен использовать существующие Coding/Review proposals и не расширять research permissions.
