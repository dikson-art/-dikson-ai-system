# Architecture

Dikson-Li is a local, model-independent project memory and research system.

Core components:

- FastAPI service for projects, sources, search, and research;
- append-only local memory for durable operational records;
- Markdown Wiki for curated project knowledge;
- specialized agents operating through reviewable proposals;
- OpenAI integration for grounded synthesis.

The architecture keeps deterministic local storage and retrieval available even when no API key is configured.
