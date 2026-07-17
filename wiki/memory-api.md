---
title: Memory API
tags:
  - memory
  - api
  - architecture
status: implemented
---

# Memory API

Memory API хранит знания проекта как append-only JSONL-журнал.

## Типы записей

- fact
- decision
- task
- hypothesis
- source
- summary

## Связи

`source_ids` связывает запись с загруженными источниками, а `related_memory_ids` — с другими записями памяти.

## API

См. [архитектуру](../docs/ARCHITECTURE.md) и маршруты `/projects/{project_id}/memory` в OpenAPI-схеме FastAPI.
