---
title: Wiki CRUD
slug: wiki-crud
tags:
  - wiki
  - markdown
  - api
status: implemented
---

# Wiki CRUD

Wiki-страница — это Markdown-файл с YAML front matter.

## Front matter

Поддерживаются `id`, `title`, `slug`, `project_id`, `kind`, `status`, `tags`, `source_ids`, `related_page_ids`, `related_memory_ids`, `created_at`, `updated_at`.

## История

Create, update и archive получают operation ID, actor, reason и UTC timestamp. Update/archive сохраняют полную предыдущую версию. DELETE переводит страницу в `archived`, не удаляя файл.

## Backlinks и поиск

Backlinks строятся из `related_page_ids` и маркеров `[[page_id]]`. Поиск нечувствителен к регистру и работает по title/Markdown; tag-фильтр работает по front matter.

## Knowledge promotion

Связь с Memory явная через ID. Hypothesis не становится подтверждённым Wiki-фактом автоматически: пользователь или агент должен создать/обновить страницу отдельной операцией с reason.

См. [Unified Architecture](../docs/UNIFIED_ARCHITECTURE.md).
