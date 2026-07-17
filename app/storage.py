import json
import re
from pathlib import Path
from uuid import uuid4

from docx import Document
from pypdf import PdfReader

from app.config import settings


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "-", value.strip()).strip("-").lower()
    return slug or uuid4().hex[:8]


def project_dir(project_id: str) -> Path:
    path = settings.dikson_data_dir / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "sources").mkdir(exist_ok=True)
    return path


def create_project(name: str, description: str = "") -> dict:
    project_id = slugify(name)
    path = project_dir(project_id)
    metadata = {"id": project_id, "name": name, "description": description, "memory": [], "decisions": []}
    (path / "project.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def load_project(project_id: str) -> dict:
    file = project_dir(project_id) / "project.json"
    if not file.exists():
        raise FileNotFoundError(project_id)
    return json.loads(file.read_text(encoding="utf-8"))


def save_project(project: dict) -> None:
    path = project_dir(project["id"]) / "project.json"
    path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    temp = settings.dikson_data_dir / f"upload-{uuid4().hex}{suffix}"
    temp.write_bytes(content)
    try:
        if suffix == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(temp).pages)
        if suffix == ".docx":
            return "\n".join(p.text for p in Document(temp).paragraphs)
        if suffix in {".txt", ".md"}:
            return content.decode("utf-8", errors="replace")
        raise ValueError("Поддерживаются PDF, DOCX, TXT и MD")
    finally:
        temp.unlink(missing_ok=True)


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks


def save_source(project_id: str, filename: str, text: str) -> dict:
    source_id = uuid4().hex[:12]
    record = {"id": source_id, "filename": filename, "chunks": chunk_text(text)}
    target = project_dir(project_id) / "sources" / f"{source_id}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": source_id, "filename": filename, "chunks": len(record["chunks"])}


def search_sources(project_id: str, query: str, limit: int = 6) -> list[dict]:
    terms = {word.lower() for word in re.findall(r"[\w-]{3,}", query)}
    matches = []
    for file in (project_dir(project_id) / "sources").glob("*.json"):
        source = json.loads(file.read_text(encoding="utf-8"))
        for index, chunk in enumerate(source["chunks"]):
            lowered = chunk.lower()
            score = sum(lowered.count(term) for term in terms)
            if score:
                matches.append({"source_id": source["id"], "filename": source["filename"], "chunk": index, "score": score, "text": chunk})
    return sorted(matches, key=lambda item: item["score"], reverse=True)[:limit]
