from pathlib import Path

from dikson_li.wiki import MarkdownWikiStore


class WikiService:
    """Application adapter that scopes the canonical Wiki store to a project."""

    def __init__(self, data_dir: Path, project_id: str) -> None:
        self.store = MarkdownWikiStore(data_dir / "projects" / project_id / "wiki")
