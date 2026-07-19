---
title: Research Engine
tags:
  - architecture
  - research
  - agents
  - planning
status: active
---

# Research Engine

Research Engine превращает вопрос в approved DAG, evidence snapshot со стабильными citations и pending `research_report` proposal. Канонические Study, Evidence и Report находятся в `dikson_li.research`.

## Инварианты

- исследование не исполняется до approve и activate;
- используются [[planning-system]], [[task-queue]], [[agent-framework]] и [[semantic-search]], а не их копии;
- один документ входит в evidence один раз с лучшим score;
- citations стабильны внутри сохранённого отчёта;
- повторный advance не создаёт второй run, task или proposal;
- Knowledge Graph связывает Study с использованными Memory, Wiki и Source entities;
- отчёт не изменяет знания без human decision.

## Режимы synthesis

Локальный режим всегда доступен и явно сообщает о пробелах. OpenAI adapter использует stateless Responses API и не меняет доменное ядро.

Git Automation реализован поверх существующих Coding и Review Agent contracts; см. [[git-automation]]. Следующий приоритет проекта — Documentation Generator.
