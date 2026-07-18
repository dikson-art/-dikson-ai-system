---
title: Agent Framework
tags:
  - architecture
  - agents
  - security
status: active
---

# Agent Framework

Семь встроенных агентов работают через единый registry и deny-by-default tool policy: Research, Planning, Memory, Wiki, Coding, Review и Documentation.

## Поток

`run → proposal → human decision → optional approved memory commit`

Runs, proposals и decisions являются append-only audit records. Они не дают агенту право напрямую изменить Memory, Wiki, Graph, код или Git.

## Память

Персональная память — это отфильтрованное представление канонического Memory Core по `agent:{id}`. Она создаётся только из подтверждённого `agent_memory` proposal и хранит reviewer/proposal metadata.

## Следующий этап

Task Queue добавит workers, leases, retries и переходы состояния выполнения. Agent Registry и policy останутся источником разрешений.
