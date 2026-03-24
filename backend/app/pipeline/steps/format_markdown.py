"""Step 5: Assemble final markdown matching existing KB format."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def format_markdown(
    structured_text: str,
    topics: dict,
    video_title: str,
    output_dir: Path,
) -> Path:
    """Build KB-format markdown from structured text and extracted topics."""
    final_path = output_dir / "final.md"
    if final_path.exists():
        logger.info("final.md already exists, skipping")
        return final_path

    lines: list[str] = []
    summary = topics.get("summary", "")
    lines.append(f"# База знаний: Вебинар — {video_title}\n")
    if summary:
        lines.append(f"_{summary}_\n")

    # Main structured content (already has ## and ### headings from step 3)
    lines.append(structured_text)

    # Check which sections already exist in structured text to avoid duplication
    text_upper = structured_text.upper()
    has_faq = "## ЧАСТО ЗАДАВАЕМЫЕ ВОПРОСЫ" in text_upper
    has_objections = "## ВОЗРАЖЕНИЯ И ОТВЕТЫ" in text_upper
    has_utp = "## КЛЮЧЕВЫЕ УТП" in text_upper
    has_social = "## СОБЫТИЯ И СООБЩЕСТВО" in text_upper

    # Append extracted FAQ only if not already in structured text
    faq_items = topics.get("faq", [])
    if faq_items and not has_faq:
        lines.append("\n## ЧАСТО ЗАДАВАЕМЫЕ ВОПРОСЫ\n")
        for item in faq_items:
            q = item.get("question", "")
            a = item.get("answer", "")
            if q and a:
                lines.append(f"### {q}\n")
                lines.append(f"{a}\n")

    # Append objections
    objections = topics.get("objections", [])
    if objections and not has_objections:
        lines.append("\n## ВОЗРАЖЕНИЯ И ОТВЕТЫ\n")
        for item in objections:
            obj = item.get("objection", "")
            resp = item.get("response", "")
            if obj and resp:
                lines.append(f"### «{obj}»\n")
                lines.append(f"{resp}\n")

    # Append sales arguments
    args = topics.get("sales_arguments", [])
    if args and not has_utp:
        lines.append("\n## КЛЮЧЕВЫЕ УТП\n")
        for arg in args:
            lines.append(f"- {arg}")
        lines.append("")

    # Append social proof
    proofs = topics.get("social_proof", [])
    if proofs and not has_social:
        lines.append("\n## СОБЫТИЯ И СООБЩЕСТВО\n")
        for proof in proofs:
            lines.append(f"- {proof}")
        lines.append("")

    # Append sales techniques
    techniques = topics.get("sales_techniques", [])
    if techniques:
        lines.append("\n## ЧЕКЛИСТ КВАЛИФИКАЦИИ\n")
        lines.append("### Техники продаж из вебинара\n")
        for tech in techniques:
            name = tech.get("technique", "")
            example = tech.get("example", "")
            context = tech.get("context", "")
            if name:
                lines.append(f"**{name}:**")
                if example:
                    lines.append(f"- Пример: «{example}»")
                if context:
                    lines.append(f"- Контекст: {context}")
                lines.append("")

    # Append speaker style
    style = topics.get("speaker_style", {})
    if style and any(style.values()):
        lines.append("\n## ШАБЛОНЫ КОММУНИКАЦИЙ\n")
        lines.append("### Стиль спикера\n")
        if style.get("tone"):
            lines.append(f"**Тон:** {style['tone']}\n")
        if style.get("opening_technique"):
            lines.append(f"**Начало вебинара:** {style['opening_technique']}\n")
        if style.get("closing_technique"):
            lines.append(f"**Завершение:** {style['closing_technique']}\n")
        phrases = style.get("key_phrases", [])
        if phrases:
            lines.append("**Ключевые фразы:**")
            for p in phrases:
                lines.append(f"- «{p}»")
            lines.append("")
        stories = style.get("storytelling_patterns", [])
        if stories:
            lines.append("**Истории и кейсы:**")
            for s in stories:
                lines.append(f"- {s}")
            lines.append("")

    # Append presentation structure
    pres = topics.get("presentation_structure", "")
    if pres:
        lines.append("\n### Структура презентации\n")
        lines.append(pres)
        lines.append("")

    result = "\n".join(lines)
    final_path.write_text(result, encoding="utf-8")
    logger.info("Final markdown saved: %d chars", len(result))
    return final_path
