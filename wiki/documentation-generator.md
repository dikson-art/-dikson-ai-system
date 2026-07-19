---
title: Documentation Generator
tags:
  - documentation
  - agents
  - openapi
---

# Documentation Generator

Documentation Generator строит API Reference и Agent Catalog из актуальных OpenAPI и [[agent-framework]] manifests. Каждый результат является immutable snapshot с SHA-256 и pending documentation proposal.

Генератор не изменяет Wiki, README или [[git-automation]] напрямую. Публикация остаётся отдельным подтверждаемым действием.
