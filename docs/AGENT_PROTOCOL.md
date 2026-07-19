# DIKSON-Li Agent Protocol

## Базовый принцип

Агенты не изменяют Memory, Wiki, Graph, код или Git напрямую. Они запускаются с явно разрешённым набором tools и создают типизированные предложения. Решение человека записывается отдельным immutable audit event.

## Роли агентов

### Research Agent

- анализирует источники и Semantic Search results;
- строит доказательную базу;
- предлагает research reports и фиксирует пробелы.
- исполняет только подтверждённые research plan steps через Task Queue lease.

### Planning Agent

- декомпозирует цели;
- определяет зависимости;
- создаёт предложения планов.

### Memory Agent

- классифицирует знания;
- ищет конфликты;
- создаёт предложения изменений Memory Core.

### Wiki Agent

- организует страницы и cross references;
- контролирует согласованность Wiki;
- создаёт предложения Wiki changes.

### Coding Agent

- анализирует код и Git state в read-only режиме;
- проектирует изменения;
- создаёт code-change proposals.

### Review Agent

- проверяет факты, логику, ссылки и код;
- оценивает риски;
- создаёт review proposals.

### Documentation Agent

- поддерживает пользовательскую и архитектурную документацию;
- готовит release notes;
- создаёт documentation proposals.

## Tool policy

Каждый запуск перечисляет `requested_tools`. Registry применяет deny-by-default правило: неизвестный или не принадлежащий роли tool отклоняет запуск до записи в журнал. Разрешение tool означает право сформировать предложение или прочитать данные, но не право изменить доменное хранилище.

## Предложения и решения

Proposal содержит agent/run IDs, тип, title, summary, JSON payload, optional `idempotency_key` и timestamp. Допустимые типы определены manifest конкретного агента. Proposal имеет статус `pending`, пока отдельное decision event не установит `approved` или `rejected`. Второе решение для того же proposal запрещено.

## Персональная память

У каждого агента есть `memory_tag` вида `agent:{agent_id}`. Agent-memory proposal обязан пройти Pydantic-валидацию `MemoryCreate` и подтверждение. После явного commit он идемпотентно записывается через канонический `JsonlMemoryStore`; отдельного agent memory store нет.

## Выполнение

Task Queue связывает Agent Run с worker через ограниченный lease. Queue отвечает за доставку, retries и lifecycle audit, но worker обязан выполнять только tools из уже подтверждённого run manifest.
