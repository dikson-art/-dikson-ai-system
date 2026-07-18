# Knowledge Graph

## Цель

Knowledge Graph связывает Projects, Memory, Tasks, Wiki Pages, Documents, Sources, People, Articles и Research без переноса владения их данными.

## Модель

Узел содержит `id`, `project_id`, `type`, `label`, `entity_id`, `properties`, `created_at`, `projected`. Ребро содержит `from_node_id`, `to_node_id`, `type`, `properties` и те же audit-поля.

Проекционные узлы и рёбра детерминированы каноническими IDs. Явные entities и edges получают стабильные UUID и сохраняются append-only.

## Поток

```text
Canonical Memory ─┐
Canonical Wiki ───┼─→ KnowledgeGraphService → Snapshot → API
Project Sources ──┘             ↑
                         JSONL Graph Repository
```

## Ограничения

- traversal пока ограничен непосредственными neighbors;
- удаление и изменение graph entities отсутствуют;
- полнотекстовый/семантический поиск будет отдельным следующим слоем;
- проекционный snapshot строится при чтении и рассчитан на текущий локальный масштаб.
