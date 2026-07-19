from app.config import settings
from app.research_service import ResearchEngineService


def answer(project_id: str, question: str) -> dict:
    return ResearchEngineService(settings.dikson_data_dir, project_id).quick_answer(question)
