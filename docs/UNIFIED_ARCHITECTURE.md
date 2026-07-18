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

## Wiki target flow

```text
FastAPI
   ↓
Wiki Service
   ↓
Markdown + YAML Front Matter
   ↓
History / Backlinks Index
```

Wiki-страницы будут связываться с памятью через `related_memory_ids`, а память уже предусматривает `related_page_ids`. Подтверждение гипотезы останется явной операцией, а не автоматическим изменением Wiki.
