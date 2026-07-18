---
title: Semantic Search
tags:
  - architecture
  - search
  - embeddings
status: active
---

# Semantic Search

Единый поиск строит живую read-only проекцию Memory, Wiki, Source chunks и явных Knowledge Graph entities. Он не владеет знаниями и не сохраняет вторую копию контента.

## Backends

- `local` — детерминированный multilingual feature hashing, работает автономно;
- `openai` — нейросетевые embeddings через официальный Embeddings API.

Оба backend реализуют один `EmbeddingModel` port. API, фильтры и формат результатов не зависят от провайдера.

## Graph context

Graph edges связывают поисковые документы по каноническим IDs. Релевантность соседней сущности даёт небольшой boost, но не перекрывает прямое совпадение.

## Инварианты

- Memory, Wiki, Sources и Graph остаются источниками истины;
- проекционные graph nodes не создают дублирующие search results;
- архив Wiki исключён по умолчанию;
- старый `/projects/{project_id}/search` остаётся совместимым;
- повреждённый source index не раскрывает внутренние пути через API.
