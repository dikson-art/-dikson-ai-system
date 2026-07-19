# Unified Architecture

## Memory flow

```text
FastAPI / CLI
      ↓
Memory Service / direct CLI adapter
      ↓
Canonical Memory Core (dikson_li.memory)
      ↓
FileLock → UTF-8 JSONL Storage
```

FastAPI проверяет существование проекта и преобразует доменные ошибки в HTTP-ответы. `MemoryService` задаёт data root. Вся валидация моделей, фильтрация, миграция, блокировка и JSONL-персистентность принадлежат каноническому core.

## Canonical record

Каждая запись содержит `id`, `project_id`, `kind`, `content`, `created_at`, `tags`, `source_ids`, `related_memory_ids`, `related_page_ids` и `metadata`.

## Append-only guarantees

Публичных операций update/delete нет. Новая информация создаёт новую запись и может ссылаться на предыдущие через `related_memory_ids`. `FileLock` сериализует процессы на одной машине; корректность блокировок на нестандартных сетевых файловых системах зависит от реализации файловой системы и пока не гарантируется.

## Wiki flow

```text
FastAPI
   ↓
Wiki Service
   ↓
Markdown + YAML Front Matter
   ↓
History / Backlinks Index
```

Wiki-страницы связываются с памятью через `related_memory_ids`, а память предусматривает `related_page_ids`. Подтверждение гипотезы остаётся явной операцией, а не автоматическим изменением Wiki.

Wiki Service задаёт project root; front matter validation, atomic write, history, backlinks, slug uniqueness и search находятся в каноническом `dikson_li.wiki`.

## Knowledge Graph flow

```text
Memory Core ─┐
Wiki Core ───┼─→ Graph Projection ─┐
Sources ─────┘                     ├─→ Graph Snapshot / Neighbors
Explicit Entities → JSONL Graph ──┘
```

Memory, Wiki и documents остаются источниками истины. Graph Projection создаёт стабильные ссылки при чтении; JSONL Repository хранит только явные внешние сущности и пользовательские связи. Такая схема исключает рассинхронизацию копий.

## Semantic Search flow

```text
Memory ─┐
Wiki ───┼─→ Live Search Projection → Embedding Port → Ranked Results
Sources ┤                              ├─ local
Graph ──┘                              └─ OpenAI
   └──────────────────── relation context ────────────↑
```

Search Projection существует только во время чтения. `SemanticSearchEngine` не знает о FastAPI, файловых путях или OpenAI SDK; он получает типизированные `SearchDocument` и реализацию `EmbeddingModel`. Source-only функция оставлена как тонкий compatibility adapter к тому же сервису, поэтому независимой второй реализации поиска нет.

## Agent Framework flow

```text
Objective + requested tools
           ↓
Agent Registry / deny-by-default policy
           ↓
Append-only Run → Proposal → Human Decision
                                  ↓ approved agent_memory
                          Canonical Memory Core
```

Agent audit streams описывают процесс, но не владеют доменными знаниями. Каждый agent memory namespace реализован стабильным tag в Memory Core. Task Queue принимает только прошедшие policy Agent Runs; будущий worker обязан выполнять tools из сохранённого run manifest.

## Task Queue flow

```text
Policy-validated Agent Run
           ↓ enqueue
Immutable Task + Event Stream
           ↓ atomic claim
Worker Lease ──heartbeat──┐
     ├─ complete → succeeded
     ├─ fail → retry / failed / dead_letter
     └─ expire → retry / dead_letter
```

Task Queue хранит orchestration state, а не знания. Worker result остаётся audit payload до преобразования специализированным агентом в proposal; доменные изменения продолжают проходить Agent Protocol и human decision.

## Planning flow

```text
Draft DAG ──human decision──→ Approved Plan
                                  ↓ activate
Dependency evaluator ───────→ Ready Steps
                                  ↓ idempotent dispatch
                  Agent Run + Queue Task
                                  ↓ task events
                 next wave / blocked / completed
```

Planning Core владеет определением DAG и audit events, но не дублирует Agent Run или Task state. `PlanningService` строит read model из plan events и канонических Task Queue states. Общий idempotency key связывает plan step, agent run и queue task, а orchestration lock сериализует dispatch/cancel внутри проекта.

```text
FastAPI → Planning Service → Planning Core (plans/events JSONL)
                    ├──────→ Agent Framework (policy + run audit)
                    └──────→ Task Queue (execution lifecycle)
```

## Research flow

```text
Research Study → Draft Research Plan → Human approve / activate
                                      ↓
                         gather-evidence task
                                      ↓
             Semantic Search → dedupe → citations E1..En
                                      ↓
                        synthesize-report task
                         ├─ local transparent fallback
                         └─ OpenAI Responses adapter
                                      ↓
                 pending research_report proposal
                                      ↓
                      Human decision / later commit
```

Research Core хранит historical evidence/report snapshots, потому что отчёт должен оставаться проверяемым даже после изменения исходных материалов. Он не копирует execution state: status читается из канонического Planning/Task read model. Research Agent policy и proposal audit принадлежат Agent Framework; поиск принадлежит Semantic Search; связи исследования строятся Knowledge Graph как read projection.

`advance` использует task-specific lease и общий project orchestration lock. Study, plan, runs, tasks и proposal имеют стабильные idempotency boundaries, поэтому повторный запрос не создаёт дубликаты после частичного сбоя.
