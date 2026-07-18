# Unified Architecture

## Memory flow

```text
FastAPI / CLI
      ↓
Memory Service / direct CLI adapter
      ↓
Canonical Memory Core (dikson_li.memory)
      ↓
FileLock → UTF-8 JSONL Storage
```

FastAPI проверяет существование проекта и преобразует доменные ошибки в HTTP-ответы. `MemoryService` задаёт data root. Вся валидация моделей, фильтрация, миграция, блокировка и JSONL-персистентность принадлежат каноническому core.

## Canonical record

Каждая запись содержит `id`, `project_id`, `kind`, `content`, `created_at`, `tags`, `source_ids`, `related_memory_ids`, `related_page_ids` и `metadata`.

## Append-only guarantees

Публичных операций update/delete нет. Новая информация создаёт новую запись и может ссылаться на предыдущие через `related_memory_ids`. `FileLock` сериализует процессы на одной машине; корректность блокировок на нестандартных сетевых файловых системах зависит от реализации файловой системы и пока не гарантируется.

## Wiki flow

```text
FastAPI
   ↓
Wiki Service
   ↓
Markdown + YAML Front Matter
   ↓
History / Backlinks Index
```

Wiki-страницы связываются с памятью через `related_memory_ids`, а память предусматривает `related_page_ids`. Подтверждение гипотезы остаётся явной операцией, а не автоматическим изменением Wiki.

Wiki Service задаёт project root; front matter validation, atomic write, history, backlinks, slug uniqueness и search находятся в каноническом `dikson_li.wiki`.

## Knowledge Graph flow

```text
Memory Core ─┐
Wiki Core ───┼─→ Graph Projection ─┐
Sources ─────┘                     ├─→ Graph Snapshot / Neighbors
Explicit Entities → JSONL Graph ──┘
```

Memory, Wiki и documents остаются источниками истины. Graph Projection создаёт стабильные ссылки при чтении; JSONL Repository хранит только явные внешние сущности и пользовательские связи. Такая схема исключает рассинхронизацию копий.
