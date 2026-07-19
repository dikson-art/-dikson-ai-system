# Task Queue

## Назначение

Task Queue превращает policy-validated Agent Run в durable единицу исполнения. Очередь не запускает shell, Git или model calls сама: worker получает lease, выполняет разрешённые tools и фиксирует результат или ошибку.

## State machine

```text
queued ──claim──→ running ──complete──→ succeeded
  ↑                 │
  │                 ├─ fail(retryable) ─→ queued
  │                 ├─ fail(non-retryable) → failed
  │                 └─ lease expired / attempts exhausted → dead_letter

queued/running ──cancel──→ cancelled
```

Task record неизменяем. Состояние вычисляется из append-only events: `claimed`, `heartbeat`, `completed`, `retry_scheduled`, `failed`, `dead_lettered`, `cancelled`.

## Связь с Agent Framework

Каждая задача содержит `run_id` и `agent_id`. Application service разрешает enqueue только для существующего Agent Run, который уже прошёл tool policy. Worker не может подменить роль при claim; опциональный `agent_id` только фильтрует доступные задачи.

## Хранение

`data/projects/{project_id}/tasks` содержит:

- `tasks.jsonl` — immutable task records;
- `events.jsonl` — lifecycle events;
- `.tasks.lock` — project-scoped межпроцессная блокировка.

Enqueue, claim и state transitions выполняются под одним `FileLock`. Каждая строка записывается через `flush` и `fsync`. Повреждённая строка вызывает `TaskCorruptionError`, преобразуемый API в безопасный HTTP 500.

## Leases

Атомарный claim выбирает доступную задачу по priority, `available_at`, времени создания и ID. Worker получает случайный lease token и срок действия от 5 до 3600 секунд. Только владелец действующего token может heartbeat, complete, fail или cancel running task.

Lease token возвращается только из `/claim`. List, get, transition responses и event history используют публичные модели без token.

Expired lease обрабатывается следующим claim: задача получает audit event и либо немедленно возвращается в queue, либо переходит в `dead_letter`, если `max_attempts` исчерпан.

## Retries и idempotency

- `max_attempts` ограничен диапазоном 1–20;
- retryable failure может задать delay до 24 часов;
- non-retryable failure сразу переводит задачу в `failed`;
- исчерпанные retry или leases переводят задачу в `dead_letter`;
- project-scoped `idempotency_key` возвращает исходную задачу без повторной записи.

## API

- `POST /projects/{project_id}/tasks` — enqueue существующего run;
- `GET /projects/{project_id}/tasks` — список с фильтром status;
- `POST /projects/{project_id}/tasks/claim` — атомарный claim;
- `GET /projects/{project_id}/tasks/{task_id}` — текущее состояние;
- `GET /projects/{project_id}/tasks/{task_id}/events` — audit history;
- `POST /projects/{project_id}/tasks/{task_id}/heartbeat` — продлить lease;
- `POST /projects/{project_id}/tasks/{task_id}/complete` — сохранить результат;
- `POST /projects/{project_id}/tasks/{task_id}/fail` — retry/fail/dead-letter;
- `POST /projects/{project_id}/tasks/{task_id}/cancel` — отменить задачу.

## Ограничения

FileLock обеспечивает локальную межпроцессную координацию. Распределённые workers на разных машинах потребуют transactional queue adapter, реализующего тот же state-machine contract. Planning System диспетчеризует ready DAG steps, а Research Engine выполняет только связанные research tasks через необязательный точечный фильтр `task_id`; общий priority claim остаётся обратно совместимым.
