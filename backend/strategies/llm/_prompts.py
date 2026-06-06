from __future__ import annotations

from backend.models import ContextWindow

_SOURCE_TYPE_LABELS = {
    "docs_site": "Documentation",
    "github": "GitHub repository",
    "pdf": "PDF document",
    "slack": "Slack messages",
}


def _format_sources(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        label = _SOURCE_TYPE_LABELS.get(s["source_type"], s["source_type"].replace("_", " ").title())
        lines.append(f"  - {label}: {s['source_url']}")
    return "\n".join(lines)


def _build_system_prompt(tenant_sources: list[dict] | None) -> str:
    if not tenant_sources:
        sources_section = (
            "This knowledge base is currently empty — no sources have been ingested yet. "
            "Let the user know they can add documentation, GitHub repositories, or PDF files "
            "via the Sources tab."
        )
    else:
        formatted = _format_sources(tenant_sources)
        sources_section = f"This knowledge base contains:\n{formatted}"

    return f"""\
You are a precise technical assistant. You answer questions using ONLY the content \
from the knowledge base described below.

{sources_section}

Rules:
- If the answer is found in the provided context: give a clear, direct answer. \
Mention the source naturally (e.g. "According to the FastAPI docs...").
- If the question is about something outside the knowledge base topics: politely say you are \
specialized for the topics listed above and cannot answer unrelated questions. \
Mention what you CAN help with.
- If asked "how can you help?", "what can you do?", or similar meta questions: describe \
the knowledge base topics listed above and invite the user to ask questions about them.
- If greeted ("hi", "hello", "thanks"): respond briefly and mention what topics you can help with.
- Never fabricate information. Never use knowledge outside the provided context.\
"""


def build_messages(context: ContextWindow) -> list[dict]:
    system_prompt = _build_system_prompt(context.tenant_sources or None)

    context_text = "\n\n---\n\n".join(
        f"[Source: {c.source_url}]\n{c.content}" for c in context.chunks
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    for turn in context.conversation_history:
        messages.append({"role": "user", "content": turn.user_message})
        messages.append({"role": "assistant", "content": turn.assistant_message})

    messages.append({
        "role": "user",
        "content": f"Context:\n{context_text}\n\nQuestion: {context.query}",
    })
    return messages
