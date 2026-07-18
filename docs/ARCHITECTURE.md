# Архитектура Dikson-Li

## Принципы

- локальные данные по умолчанию;
- прозрачные UTF-8 форматы;
- append-only история знаний;
- воспроизводимые действия;
- отделение доменного ядра от FastAPI и конкретной языковой модели;
- обязательное логирование изменений агентами.

## Слои

- `dikson_li` — канонические модели и доменное ядро;
- `app` — FastAPI, application services и HTTP-адаптеры;
- `data/projects` — локальные данные проектов;
- `wiki` — Markdown-документация проекта и страницы Wiki Engine.

## Memory

Единственное ядро памяти находится в `dikson_li.memory`. `app.memory_service` является тонким адаптером путей и не содержит логики хранения. CLI использует тот же `JsonlMemoryStore`.

Запись защищена межпроцессным `FileLock`, выполняется одной UTF-8 строкой, затем вызываются `flush` и `fsync`. Чтение также выполняется под lock. Пустые строки пропускаются; повреждённые строки вызывают `MemoryCorruptionError`, который API преобразует в безопасный HTTP 500.

Старый формат `data/memory/{project}.jsonl` мигрирует при первом чтении. Детерминированные UUID сохраняют стабильность повторной миграции; старый тип `note` преобразуется в `fact`.

## Пакетирование

Python-дистрибутив явно включает пакеты `app` и `dikson_li`. Каталоги данных `data` и `wiki` не участвуют в package discovery.

## Следующие слои

1. Реестр агентов и skills.
2. Очередь задач и журнал запусков.
3. Planning System.
4. Research Engine.
5. Локальный web-интерфейс.

## Wiki

`dikson_li.wiki.MarkdownWikiStore` является каноническим Wiki-ядром. `app.wiki_service` только задаёт project-scoped путь. Страницы хранятся как Markdown с YAML front matter; PyYAML используется только через `safe_load` и `safe_dump`.

Каждое update/archive сначала сохраняет предыдущую страницу в `history/{page_id}` вместе с actor, reason, operation ID и UTC timestamp. DELETE выполняет soft archive. Запись страниц и snapshots атомарна через временный файл, `fsync` и `os.replace`; операции проекта сериализуются `FileLock`.

Backlinks вычисляются по `related_page_ids` и ссылкам `[[page_id]]`. Поиск охватывает заголовок и Markdown-текст, фильтр тегов использует front matter.

## Knowledge Graph

`app.graph_service.KnowledgeGraphService` объединяет динамическую проекцию канонических Memory/Wiki/Source данных и явные сущности из `dikson_li.graph.JsonlGraphRepository`. Проекция не сохраняет копии контента: узлы содержат стабильные entity IDs и минимальные индексируемые свойства.

Явные graph nodes/edges являются append-only JSONL. Project-scoped `FileLock`, `flush` и `fsync` защищают запись. Повреждённая строка вызывает `GraphCorruptionError` и безопасный HTTP 500.

Типы узлов: project, memory, wiki_page, source, document, person, article, task, research. Типы рёбер: contains, relates_to, references, derived_from, supports, contradicts, depends_on, mentions.

## Semantic Search

`dikson_li.search.SemanticSearchEngine` является каноническим ядром ранжирования и зависит только от порта `EmbeddingModel`. `app.search_service.SemanticSearchService` проецирует Memory, Wiki, Source chunks и явные Graph nodes, не записывая копию контента.

Локальный backend использует детерминированный multilingual feature hashing; OpenAI adapter подключается конфигурацией и вызывает batch Embeddings API. Косинусное сходство дополняется ограниченным graph context boost. Проекционные graph nodes Memory/Wiki/Source не создают повторных результатов.
