---
title: Knowledge Graph
slug: knowledge-graph
tags:
  - graph
  - memory
  - wiki
status: implemented
---

# Knowledge Graph

Граф связывает Memory, Wiki и Documents по стабильным IDs, не копируя их канонический контент.

## Проекция

- `project:{id}` — проект;
- `memory:{id}` — память или task;
- `wiki:{id}` — Wiki-страница;
- `source:{id}` — source/document.

People, Articles и Research создаются как явные entities. Пользовательские связи сохраняются в project-scoped JSONL.

## Связи

Поддерживаются contains, relates_to, references, derived_from, supports, contradicts, depends_on и mentions.

См. [Knowledge Graph Architecture](../docs/KNOWLEDGE_GRAPH.md) и [Unified Architecture](../docs/UNIFIED_ARCHITECTURE.md).
