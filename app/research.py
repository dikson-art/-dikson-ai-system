from openai import OpenAI

from app.config import settings
from app.storage import load_project, search_sources


def answer(project_id: str, question: str) -> dict:
    project = load_project(project_id)
    evidence = search_sources(project_id, question)
    if not evidence:
        return {
            "answer": "В материалах проекта не найдено достаточно данных для ответа.",
            "evidence": [],
            "used_model": False,
        }

    context = "\n\n".join(
        f"[{item['filename']} — фрагмент {item['chunk']}]\n{item['text']}" for item in evidence
    )
    if not settings.openai_api_key:
        return {
            "answer": "Релевантные фрагменты найдены. Добавьте OPENAI_API_KEY, чтобы получить синтезированный ответ.",
            "evidence": evidence,
            "used_model": False,
        }

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=(
            "Ты исследовательский агент DIKSON. Отвечай только по предоставленным материалам. "
            "Не выдумывай страницы, авторов и факты. При нехватке данных скажи об этом. "
            "После каждого существенного утверждения указывай источник в квадратных скобках."
        ),
        input=(
            f"Проект: {project['name']}\nОписание: {project.get('description', '')}\n"
            f"Вопрос: {question}\n\nМатериалы:\n{context}"
        ),
    )
    return {"answer": response.output_text, "evidence": evidence, "used_model": True}
