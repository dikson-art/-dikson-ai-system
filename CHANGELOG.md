# Changelog

Все заметные изменения проекта документируются в этом файле.

## Unreleased
### Added

- Добавлено единое типизированное Memory Core для FastAPI и CLI с фильтрами, связями, Unicode и безопасной межпроцессной записью.
- Добавлена одноразовая миграция старых CLI JSONL-журналов с детерминированными ID.
- Добавлены сквозные и отказоустойчивые тесты API, CLI и core.

### Changed

- CLI и FastAPI теперь используют общий `DIKSON_DATA_DIR` и канонический путь `data/projects/{project_id}/memory.jsonl`.

### Fixed

- Исправлена editable- и wheel-установка: setuptools теперь явно собирает пакеты `app` и `dikson_li`, не принимая каталоги данных за Python-пакеты.
