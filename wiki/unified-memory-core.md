---
title: Unified Memory Core
slug: unified-memory-core
tags:
  - memory
  - architecture
  - api
status: implemented
---

# Unified Memory Core

FastAPI и CLI используют `dikson_li.memory.JsonlMemoryStore`.

## Запись

Memory хранится в `data/projects/{project_id}/memory.jsonl`. Записи только добавляются; update и delete отсутствуют. Межпроцессный lock предотвращает перемешивание строк при параллельных append.

## Типы

- fact
- decision
- task
- hypothesis
- source
- summary

## Связи

- `source_ids` — загруженные источники;
- `related_memory_ids` — другие записи памяти;
- `related_page_ids` — будущие Wiki-страницы.

## Документация

См. [Unified Architecture](../docs/UNIFIED_ARCHITECTURE.md) и [Architecture](../docs/ARCHITECTURE.md).
