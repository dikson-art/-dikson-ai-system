# Unified Dikson-Li Architecture

The project now combines two complementary layers:

1. `app/` — FastAPI project, source ingestion, lexical retrieval, and OpenAI research responses.
2. `dikson_li/` — append-only local memory primitives and the `dikson-li` command-line interface.

## Data ownership

- API project metadata and imported sources live under `data/projects/`.
- Append-only operational memory lives under `data/memory/`.
- Wiki pages will live under `wiki/` and must reference their provenance.

## Integration rule

The API layer must not silently promote model output into confirmed memory. New facts, decisions, and tasks are proposals until explicitly confirmed.

## Next implementation milestone

- expose append-only memory through FastAPI;
- add Wiki page CRUD;
- add provenance links from Wiki pages to imported source chunks;
- add semantic retrieval without removing deterministic lexical fallback.
