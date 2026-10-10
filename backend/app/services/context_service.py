"""
Context Prompt & Biasing Service
Constructs domain-specific base prompts, custom vocabularies, and pedagogical context blocks
from user-defined kindergarten recording context (child, parents, staff, friends, keywords, routine).
"""

from typing import Dict, Any, Optional, List


DEFAULT_BASE_DESCRIPTION = (
    "הקלטת יום בגן ילדים ומעון יום בישראל. "
    "מטרת ההקלטה: ניטור פדגוגי של שגרת היום, אקלים הגן, יחס הצוות החינוכי ורווחתו הרגשית והבטיחותית של הילד. "
    "צלילים ואירועים צפויים בהקלטה: כניסת בוקר ומפגש פרידה מההורים, שיחות בין הורים לצוות, "
    "משחק חופשי, מפגש בוקר ושירי מעגל, משחקים בחצר, ארוחות (ארוחת בוקר/עשר/צהריים), "
    "שעת מנוחה והירדמות, ואיסוף בסוף היום. "
    "קולות דיבור של גננות, סייעות, ילדים והורים, בכי ומצוקה, צחוק, שירים, בקשות עזרה או מוצץ, והרגעה."
)


def build_stt_biasing_prompt(context: Optional[Dict[str, Any]] = None) -> str:
    """
    Builds a rich, domain-focused base prompt for STT models (ElevenLabs Scribe v2, OpenAI Whisper, etc.)
    describing the setting, the purpose of recording, what is expected to be heard,
    and all recording-specific names (child, parents, staff, friends, objects).
    """
    if not context:
        return (
            f"{DEFAULT_BASE_DESCRIPTION} "
            f"מילות מפתח עיקריות: גן ילדים, גננת, סייעת, מוצץ, בקבוק, חצר, בכי, מפגש, ארוחה, מנוחה, הורים."
        )

    child_name = (context.get("target_child_name") or "").strip()
    parents_names = (context.get("parents_names") or "").strip()
    kindergarten_name = (context.get("kindergarten_name") or "").strip()
    staff_names = (context.get("staff_names") or "").strip()
    friends_names = (context.get("friends_names") or "").strip()
    key_vocabulary = (context.get("key_vocabulary") or "").strip()
    custom_notes = (context.get("custom_notes") or "").strip()

    sections = [DEFAULT_BASE_DESCRIPTION]

    roster_parts = []
    if kindergarten_name:
        roster_parts.append(f"גן: {kindergarten_name}")
    if child_name:
        roster_parts.append(f"ילד/ה במוקד: {child_name}")
    if parents_names:
        roster_parts.append(f"הורים: {parents_names}")
    if staff_names:
        roster_parts.append(f"צוות חינוכי: {staff_names}")
    if friends_names:
        roster_parts.append(f"חברים וילדים: {friends_names}")
    if key_vocabulary:
        roster_parts.append(f"חפצים ומילות מפתח: {key_vocabulary}")
    if custom_notes:
        roster_parts.append(f"דגש ליום זה: {custom_notes}")

    if roster_parts:
        sections.append("רשימת משתתפים ומונחים בהקלטה: " + "; ".join(roster_parts) + ".")

    return "\n\n".join(sections)


def extract_custom_vocabulary(context: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Extracts individual words and phrases for STT providers that accept a custom vocabulary list (e.g. Gladia).
    """
    base_vocab = ["מוצץ", "בקבוק", "שמיכי", "גננת", "סייעת", "מפגש", "חצר", "ארוחה", "בכי"]
    if not context:
        return base_vocab

    vocab_set = set(base_vocab)

    for key in ["target_child_name", "parents_names", "kindergarten_name", "staff_names", "friends_names", "key_vocabulary"]:
        val = context.get(key)
        if isinstance(val, str) and val.strip():
            # Split by commas or semicolons
            chunks = [c.strip() for c in val.replace(";", ",").replace("\n", ",").split(",") if c.strip()]
            for chunk in chunks:
                # Remove parentheses notes like "(גננת)"
                clean_chunk = chunk.split("(")[0].strip()
                if clean_chunk:
                    vocab_set.add(clean_chunk)
                    for word in clean_chunk.split():
                        if len(word) >= 2:
                            vocab_set.add(word)

    return sorted(list(vocab_set))


def build_pedagogical_context_block(context: Optional[Dict[str, Any]] = None) -> str:
    """
    Builds a structured Hebrew Markdown block describing the recording context
    for the pedagogical report LLM and the chat assistant.
    """
    if not context:
        return ""

    lines = ["### הקשר ההקלטה ופרופיל הגן:"]

    if context.get("kindergarten_name"):
        lines.append(f"- **שם הגן / המסגרת**: {context['kindergarten_name']}")
    if context.get("target_child_name"):
        lines.append(f"- **הילד/ה במוקד**: {context['target_child_name']}")
    if context.get("parents_names"):
        lines.append(f"- **שמות ההורים**: {context['parents_names']}")
    if context.get("staff_names"):
        lines.append(f"- **צוות הגן ותפקידים**: {context['staff_names']}")
    if context.get("friends_names"):
        lines.append(f"- **חברים וילדים נוספים**: {context['friends_names']}")
    if context.get("key_vocabulary"):
        lines.append(f"- **מילות מפתח וחפצי מעבר**: {context['key_vocabulary']}")
    if context.get("custom_notes"):
        lines.append(f"- **דגשים מיוחדים להקלטה זו**: {context['custom_notes']}")

    return "\n".join(lines) if len(lines) > 1 else ""


def extract_tagging_suggestions(context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Builds suggested speaker tags for the tagging modal UI chips.
    Returns list of dicts: [{"name": "...", "role": "...", "is_focus": bool, "category": "..."}]
    """
    if not context:
        return []

    suggestions: List[Dict[str, Any]] = []

    # 1. Target child
    child = (context.get("target_child_name") or "").strip()
    if child:
        suggestions.append({
            "name": child,
            "role": "ילד/ה במוקד",
            "is_focus": True,
            "category": "child"
        })

    # 2. Parents
    parents = (context.get("parents_names") or "").strip()
    if parents:
        for p in [x.strip() for x in parents.replace(";", ",").replace(" ו", ",").split(",") if x.strip()]:
            clean_p = p.split("(")[0].strip()
            if clean_p:
                suggestions.append({
                    "name": clean_p,
                    "role": "הורה",
                    "is_focus": False,
                    "category": "parent"
                })

    # 3. Staff
    staff = (context.get("staff_names") or "").strip()
    if staff:
        for s in [x.strip() for x in staff.replace(";", ",").split(",") if x.strip()]:
            role = "סייעת" if "סייעת" in s else ("גננת ראשית" if "גננת" in s else "צוות חינוכי")
            clean_s = s.split("(")[0].strip()
            if clean_s:
                suggestions.append({
                    "name": clean_s,
                    "role": role,
                    "is_focus": False,
                    "category": "staff"
                })

    # 4. Friends
    friends = (context.get("friends_names") or "").strip()
    if friends:
        for f in [x.strip() for x in friends.replace(";", ",").split(",") if x.strip()]:
            clean_f = f.split("(")[0].strip()
            if clean_f:
                suggestions.append({
                    "name": clean_f,
                    "role": "חבר/ה לגן",
                    "is_focus": False,
                    "category": "friend"
                })

    return suggestions
