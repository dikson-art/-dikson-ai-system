---
title: Task Queue
tags:
  - architecture
  - agents
  - queue
status: active
---

# Task Queue

Durable очередь связывает policy-validated Agent Run с worker execution. Task immutable, а состояние восстанавливается из append-only events.

## Гарантии

- атомарный claim под project-scoped lock;
- priority и delayed availability;
- lease token и heartbeat;
- retries, non-retryable failure и dead-letter;
- project-scoped idempotency key;
- cancellation и полная audit history;
- lease token виден только worker в ответе claim.

## Граница

Queue управляет доставкой и состоянием, но не знает, как выполнять конкретный Agent Tool. [[planning-system]] диспетчеризует ready DAG steps поверх стабильного queue contract; Research Engine добавит специализированное выполнение исследовательских payloads.
