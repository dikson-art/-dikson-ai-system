# Planning System

## Назначение

Planning System преобразует подтверждённую цель в управляемый DAG шагов. Он отвечает за зависимости, human approval и диспетчеризацию, но не выполняет tools и не владеет результатами работы агентов.

## Слои

- `dikson_li.planning` — модели, DAG-валидация, lifecycle rules и append-only JSONL repository;
- `app.planning_service` — agent policy, вычисление read model и интеграция с Agent Framework/Task Queue;
- `app.planning_api` — project-scoped HTTP adapter и безопасное отображение ошибок.

Данные проекта расположены в `data/projects/{project_id}/plans`:

- `plans.jsonl` — неизменяемые определения планов;
- `events.jsonl` — решения, активация, отмена и факты dispatch;
- `.plans.lock` — защита repository operations;
- `.orchestration.lock` — сериализация dispatch и cancel между процессами.

## Модель DAG

Каждый шаг содержит стабильный ID, цель, agent role, requested tools, зависимости, критерии приёмки, priority и max attempts. При создании проверяются:

1. уникальность step IDs;
2. существование каждой зависимости;
3. отсутствие self-dependency;
4. отсутствие циклов;
5. соответствие tools allowlist выбранного агента.

Порядок шагов во входном документе не обязан быть топологическим.

## Lifecycle

```text
draft ──approve──→ approved ──activate──→ active
  ├──reject──→ rejected                    ├── all succeeded → completed
  └──cancel──→ cancelled                   ├── terminal step failure → blocked
                                           └── cancel → cancelled
```

`completed` и `blocked` вычисляются из Task Queue при чтении. Они не записываются как альтернативное состояние и потому не могут расходиться с очередью.

Статусы шагов:

- `blocked` — план не активен или зависимости ещё не завершены;
- `ready` — все зависимости завершены успешно;
- `queued`, `running`, `succeeded`, `failed`, `dead_letter`, `cancelled` — проекция канонического task status.

## Надёжная диспетчеризация

Для шага используется ключ `plan:{plan_id}:step:{step_id}`. Один и тот же ключ записывается в Agent Run и Queue Task. Повторный запрос или восстановление после сбоя возвращает уже созданные записи; dispatch event также записывается не более одного раза.

Orchestration lock предотвращает одновременные dispatch и cancel. Если процесс завершится между созданием run/task и plan event, следующий dispatch безопасно восстановит связь. JSONL append использует `flush` и `fsync`.

Отмена плана прекращает будущий dispatch. Уже выданная worker lease остаётся ответственностью Task Queue и должна отменяться через task API при необходимости. Завершённый план отменить нельзя.

## HTTP API

| Метод | Endpoint | Назначение |
|---|---|---|
| `POST` | `/projects/{project_id}/plans` | Создать draft |
| `GET` | `/projects/{project_id}/plans` | Список, фильтр `status` |
| `GET` | `/projects/{project_id}/plans/{plan_id}` | Read model плана |
| `POST` | `.../{plan_id}/decision` | Approve/reject |
| `POST` | `.../{plan_id}/activate` | Активировать approved plan |
| `POST` | `.../{plan_id}/dispatch` | Отправить текущую ready wave |
| `POST` | `.../{plan_id}/cancel` | Остановить план |

Нарушение lifecycle возвращает HTTP 409, agent policy — 403, отсутствующий ресурс — 404, повреждённое локальное хранилище — безопасный 500 без раскрытия строки данных.

## Архитектурные границы

- Planning System не создаёт второй Agent Registry или Queue;
- состояние исполнения читается из Task Queue;
- доменные знания проходят через Agent Proposal и human decision;
- Research Engine будет формировать и исполнять исследовательские планы поверх этого контракта, не добавляя второй планировщик.
