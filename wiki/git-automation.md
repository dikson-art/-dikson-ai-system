---
title: Git Automation
tags:
  - git
  - agents
  - automation
---

# Git Automation

Git Automation исполняет только подтверждённые `code_change` proposals [[agent-framework]]. Каноническое ядро читает status/diff и создаёт один коммит в новой ветке `agent/*` через временный worktree.

## Инварианты

- human approval обязателен;
- активный checkout не меняется;
- `expected_head` защищает базу патча;
- hooks, shell, push и merge недоступны;
- один proposal имеет один append-only execution audit;
- ошибка требует нового proposal, а не скрытого повторного изменения.

[[documentation-generator]] использует [[agent-framework]] и результаты Git Automation без обхода approval boundary. Следующий приоритет — локальный web-интерфейс.
