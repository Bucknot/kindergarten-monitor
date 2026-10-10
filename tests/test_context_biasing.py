import pytest
from backend.app.services.context_service import (
    build_stt_biasing_prompt,
    extract_custom_vocabulary,
    build_pedagogical_context_block,
    extract_tagging_suggestions
)


def test_build_stt_biasing_prompt_contains_setting_purpose_and_sounds():
    prompt = build_stt_biasing_prompt(None)
    assert "גן ילדים" in prompt
    assert "ניטור פדגוגי" in prompt
    assert "בכי ומצוקה" in prompt
    assert "ארוחה" in prompt
    assert "חצר" in prompt
    assert "הורים" in prompt


def test_build_stt_biasing_prompt_with_custom_context():
    ctx = {
        "target_child_name": "אריאל",
        "parents_names": "דנה ויוסי",
        "kindergarten_name": "גן סביון",
        "staff_names": "רונית (גננת), מירב (סייעת)",
        "friends_names": "עומר, ליה, איתי",
        "key_vocabulary": "מוצץ, שמיכי, בקבוק",
        "custom_notes": "הייתה גננת מחליפה בבוקר"
    }
    prompt = build_stt_biasing_prompt(ctx)
    assert "אריאל" in prompt
    assert "דנה ויוסי" in prompt
    assert "גן סביון" in prompt
    assert "רונית (גננת), מירב (סייעת)" in prompt
    assert "עומר, ליה, איתי" in prompt
    assert "מוצץ, שמיכי, בקבוק" in prompt
    assert "הייתה גננת מחליפה בבוקר" in prompt
    # Check that base context setting and expected sounds are present
    assert "גן ילדים ומעון יום בישראל" in prompt
    assert "ניטור פדגוגי של שגרת היום" in prompt


def test_extract_custom_vocabulary():
    ctx = {
        "target_child_name": "אריאל",
        "parents_names": "דנה, יוסי",
        "kindergarten_name": "סביון",
        "staff_names": "רונית (גננת), מירב (סייעת)",
        "friends_names": "עומר",
        "key_vocabulary": "שמיכי"
    }
    vocab = extract_custom_vocabulary(ctx)
    assert "אריאל" in vocab
    assert "דנה" in vocab
    assert "יוסי" in vocab
    assert "רונית" in vocab
    assert "מירב" in vocab
    assert "שמיכי" in vocab
    assert "מוצץ" in vocab


def test_build_pedagogical_context_block():
    ctx = {
        "target_child_name": "סביון",
        "parents_names": "אדר ושיר",
        "kindergarten_name": "גן השושנים",
        "staff_names": "חנה",
        "custom_notes": "לבדוק אירוע חצר"
    }
    block = build_pedagogical_context_block(ctx)
    assert "### הקשר ההקלטה ופרופיל הגן:" in block
    assert "סביון" in block
    assert "אדר ושיר" in block
    assert "גן השושנים" in block
    assert "חנה" in block
    assert "לבדוק אירוע חצר" in block


def test_extract_tagging_suggestions():
    ctx = {
        "target_child_name": "סביון",
        "parents_names": "אבא דורון, אמא רחל",
        "staff_names": "מיכל (גננת), עליזה (סייעת)",
        "friends_names": "דני, יונתן"
    }
    suggestions = extract_tagging_suggestions(ctx)
    names = [s["name"] for s in suggestions]
    roles = [s["role"] for s in suggestions]

    assert "סביון" in names
    assert any(s["is_focus"] for s in suggestions if s["name"] == "סביון")
    assert "אבא דורון" in names
    assert "אמא רחל" in names
    assert "הורה" in roles
    assert "מיכל" in names
    assert "גננת ראשית" in roles
    assert "עליזה" in names
    assert "סייעת" in roles
    assert "דני" in names
    assert "חבר/ה לגן" in roles
