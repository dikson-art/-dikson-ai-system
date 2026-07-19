# Git Automation

## Назначение

Git Automation безопасно превращает рассмотренный человеком Coding Agent proposal в локальную ветку и коммит. Компонент не публикует изменения и не объединяет ветки: push и merge остаются отдельными действиями с отдельной авторизацией.

## Границы архитектуры

- `dikson_li.git_automation` — модели, policy, Git CLI port/adapter, worktree orchestration и append-only audit repository;
- `app.git_service` — проверка Agent Framework approval и преобразование payload в `GitChangeSet`;
- `app.git_api` — HTTP adapter без собственной Git-логики;
- `GIT_REPOSITORIES_DIR/{project_id}` — заранее настроенный корень Git-репозитория;
- `data/projects/{project_id}/git/executions.jsonl` — журнал запусков и итогов.

Отдельного Git executor или альтернативной модели исполнения нет.

## Контракт proposal

Coding Agent создаёт proposal типа `code_change` с payload:

```json
{
  "branch": "agent/fix-memory-index",
  "commit_message": "Fix memory index",
  "patch": "diff --git ...",
  "base_ref": "HEAD",
  "expected_head": "0123456789abcdef..."
}
```

`expected_head` рекомендуется всегда: несовпадение останавливает выполнение до изменения репозитория. Ветка обязана находиться в namespace `agent/*` и не должна существовать.

## Безопасность

- исполняется фиксированный allowlist Git-команд, а не пользовательские argv;
- `subprocess.run` получает список аргументов и `shell=False`;
- patch передаётся как UTF-8 bytes через stdin и сначала проходит `git apply --check --index`;
- Git hooks, GPG signing и terminal prompts отключены;
- system/global Git config изолирован от automation; на Windows сохраняется только безопасная нормализация `core.autocrlf=true`, которую может переопределить локальная настройка репозитория;
- репозитории с настроенными clean/smudge/process content filters отклоняются;
- изменение применяется во временном detached worktree;
- активная ветка и незакоммиченные файлы основного checkout не изменяются;
- ошибка удаляет временный worktree и созданную этим запуском ветку;
- push, merge, force push, reset и удаление существующих веток не реализованы.

## API

- `GET /projects/{project_id}/git/status`;
- `GET /projects/{project_id}/git/diff?staged=false`;
- `GET /projects/{project_id}/git/executions`;
- `POST /projects/{project_id}/git/proposals/{proposal_id}/execute` с `{ "actor": "..." }`.

Повторный execute одного proposal возвращает существующий успешный результат. Failed execution также остаётся терминальным: для изменённого патча требуется новый proposal и новое human decision.

## Рассмотренные альтернативы

- Прямое выполнение в рабочем checkout отклонено: частичная ошибка могла бы оставить индекс и файлы изменёнными.
- Произвольный Git command endpoint отклонён: его невозможно надёжно ограничить доменной policy.
- Отдельная копия approval state отклонена: источником истины остаётся Agent Framework.
- Автоматический push/PR отклонён для этого этапа: локальный commit и внешняя публикация требуют разных полномочий.
