# Agent Protocol

Dikson-Li agents operate through explicit proposals rather than silent mutation of confirmed knowledge.

## Roles

- Memory Agent: classifies and proposes durable memory entries.
- Research Agent: retrieves sources and records provenance.
- Writer Agent: drafts text from confirmed project context.
- Review Agent: checks evidence, contradictions, and unsupported claims.

## Required output fields

Every agent action should identify its role, project, input references, proposed changes, confidence, and unresolved questions.

## Safety rule

Generated content is not confirmed knowledge. Promotion to durable memory requires an explicit confirmation step.
