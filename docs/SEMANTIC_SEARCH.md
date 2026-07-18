# Semantic Search

## Цель

Semantic Search предоставляет единый ранжированный поиск по Memory, Wiki, загруженным источникам и явным сущностям Knowledge Graph. Доменные хранилища остаются источниками истины: поисковый слой не сохраняет копии документов или векторов.

## Архитектура

```text
Memory Core ─────┐
Wiki Core ───────┼─→ Search Projection → Embedding Port → Cosine Ranking
Source Chunks ───┤                            ↑               ↑
Graph Entities ──┘                   local / OpenAI     Graph context
```

`dikson_li.search` содержит модели проекции, порт `EmbeddingModel`, локальный детерминированный vectorizer и `SemanticSearchEngine`. `app.search_service` собирает project-scoped корпус, преобразует graph edges в контекстные связи и подключает конкретный embeddings-адаптер.

## Источники

- Memory: `content`, kind и tags;
- активные Wiki pages: title, Markdown content и tags;
- Sources: каждый сохранённый chunk как отдельный результат;
- Graph: только явные внешние nodes. Проекционные Memory/Wiki/Source nodes повторно не индексируются.

Архивированные Wiki pages исключены по умолчанию и включаются параметром `include_archived=true`.

## Ранжирование

Локальный backend использует нормализованные word, prefix, word-bigram и character-trigram признаки, feature hashing и cosine similarity. Лексическое покрытие стабилизирует точные совпадения, а связи Knowledge Graph добавляют ограниченный context boost связанным сущностям.

Локальный backend воспроизводим и работает без сети, но не заменяет нейросетевую модель для сложных синонимов. Для полноценных semantic embeddings задайте:

```dotenv
SEARCH_EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

OpenAI-адаптер использует batch-вызов Embeddings API с `encoding_format="float"`. По умолчанию применяется `SEARCH_EMBEDDING_PROVIDER=local`.

## API

`GET /projects/{project_id}/search` принимает:

- `q` — непустой запрос;
- `entity_type` — `memory`, `wiki_page`, `source` или `graph_node`;
- `limit` — от 1 до 100;
- `min_score` — от 0 до 1;
- `include_archived` — включить архив Wiki.

Ответ сохраняет контейнер `{"results": [...]}` и source-поля `source_id`, `filename`, `chunk`, поэтому существующие клиенты поиска загруженных документов продолжают работать.

## Ограничения

Проекция и vectors строятся на чтении. Это исключает stale index и достаточно для локального MVP, но большие коллекции потребуют content-addressed cache и пакетного обновления индекса. Такой cache должен оставаться производным и безопасно пересоздаваться из канонических данных.
