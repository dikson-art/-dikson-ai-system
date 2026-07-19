---
title: Planning System
tags:
  - architecture
  - planning
  - agents
  - task-queue
status: active
---

# Planning System

Planning System хранит подтверждаемый DAG работы и диспетчеризует только готовые шаги. Канонические определения и события находятся в `dikson_li.planning`; `PlanningService` соединяет их с Agent Framework и Task Queue.

## Инварианты

- DAG не содержит неизвестных зависимостей, self-links и циклов;
- tools каждого шага разрешены manifest выбранного агента;
- draft нельзя выполнить без approve и activate;
- один step создаёт не более одного Agent Run и Queue Task;
- task lifecycle не копируется в plan storage, а проецируется при чтении;
- ошибка, dead-letter или отмена шага блокирует план;
- все успешные шаги завершают план.

## Связи

- [[agent-framework]] — роли, policy и audit runs;
- [[task-queue]] — leases, retries и terminal execution states;
- [[unified-memory-core]] — подтверждённые знания, но не orchestration state;
- [[semantic-search]] — источник контекста для будущих исследовательских планов.

[[research-engine]] использует этот DAG и существующую очередь, не создавая собственную систему планирования.
