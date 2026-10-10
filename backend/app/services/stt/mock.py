import asyncio
import random
from typing import List
from backend.app.services.stt.base import BaseSTTProvider, STTResult, STTUtterance, STTSpeaker


class MockSTTProvider(BaseSTTProvider):
    """
    Simulates authentic Hebrew kindergarten speech with realistic speaker diarization
    and timeline distribution matching the audio duration.
    """
    def __init__(self):
        self.script_templates = [
            # Morning arrival
            ("speaker_0", "בוקר טוב ילדים חמודים, ברוכים הבאים לגן! בואו נשים את התיקים במגירות."),
            ("speaker_1", "בוקר טוב! מי רוצה כוס מים או לשבת לצייר בשולחן היצירה?"),
            ("speaker_2", "בוקר טוב מיכל, הבאתי את המכונית החדשה שלי להראות לכולם."),
            ("speaker_0", "איזו מכונית יפה! שים אותה במגירה ונוכל לשחק איתה בחצר אחר כך."),
            
            # Circle time / Morning gathering
            ("speaker_0", "ילדים, כולם לשבת במעגל של הבוקר, בואו נשיר את שיר הבוקר ביחד."),
            ("speaker_4", "שלום לכם, שלום לכם, שלום לכם שלום, ומה שלומכם ומה שלומכם היום?"),
            ("speaker_0", "מי התורן שלנו היום שיעזור לחלק את המפיות?"),
            ("speaker_3", "אני רוצה להיות תורן! אני יודע לחלק!"),
            ("speaker_0", "היום התורנים הם סביון ומיה. סביון, אתה מוכן לעזור?"),
            ("speaker_2", "כן! אני מחלק את המפיות הכחולות!"),
            
            # Snack time
            ("speaker_1", "ילדים, כולם לגשת לכיור ולרחוץ ידיים עם סבון לפני האוכל."),
            ("speaker_2", "רחצתי ידיים וניגבתי טוב טוב במגבת."),
            ("speaker_1", "כל הכבוד חמוד. מי רוצה כריך עם גבינה ומי עם טחינה?"),
            ("speaker_2", "אני רוצה עם גבינה ועגבניה בבקשה."),
            ("speaker_0", "בתאבון לכולם, ללעוס בנחת ולא לקום עם אוכל בפה."),

            # Free play & Yard time
            ("speaker_0", "יופי, עכשיו נסדר את השולחנות ויוצאים לחצר לשחק!"),
            ("speaker_3", "סביון, בוא נבנה ארמון ענק בארגז החול!"),
            ("speaker_2", "יש! אני מביא את הדלי והכף הצהובה."),
            ("speaker_3", "לא, הכף הצהובה שלי! אני לקחתי אותה קודם!"),
            ("speaker_2", "(בוכה) אבל אני רציתי אותה... הוא דחף אותי!"),
            ("speaker_0", "מה קרה כאן בחול? דני, לא דוחפים בשום אופן. סביון חמוד, בוא אליי, קיבלת מכה?"),
            ("speaker_2", "(יבבות) הוא לקח לי את הכף ודחף אותי בחול..."),
            ("speaker_0", "בוא ננקה את החול מהברכיים. הנה, קח חיבוק. דני, בוא תבקש סליחה מסביון ותביא לו כף אחרת, יש לנו שתי כפות."),
            ("speaker_3", "סליחה סביון, הנה הכף הירוקה, היא אפילו יותר גדולה."),
            ("speaker_2", "תודה. בוא נחפור ביחד בור עמוק."),
            ("speaker_1", "כל הכבוד שפתרתם את זה יפה. מי שרוצה לשתות מים, הבקבוקים פה על השולחן."),

            # Activity & Lunch
            ("speaker_0", "ילדים, זמן להיכנס פנימה. היום אנחנו לומדים על עונות השנה."),
            ("speaker_2", "בסתיו יש עלים צהובים ורוח חזקה!"),
            ("speaker_0", "נכון מאוד סביון! תשובה מצוינת. עכשיו כל אחד מקבל דף ומדביק עלים."),
            ("speaker_1", "האוכל החם הגיע! היום יש פתיתים, קציצות ואפונה."),
            ("speaker_2", "אני אוהב קציצות! אפשר עוד קציצה בבקשה?"),
            ("speaker_1", "בטח חמוד, סיימת את כל הצלחת יפה מאוד."),

            # Rest time & Departure
            ("speaker_0", "ילדים, שוכבים לנוח על המזרנים. נשמע מוזיקה שקטה ונקרא את הסיפור על הארנב."),
            ("speaker_2", "אני רוצה את השמיכה עם הכוכבים."),
            ("speaker_1", "הנה השמיכה שלך חמוד, תנוח קצת."),
            ("speaker_0", "צוהריים טובים לכולם, ההורים כבר מתחילים להגיע. שיהיה לכולם המשך יום נפלא!")
        ]

    async def transcribe(
        self,
        audio_path: str,
        duration_seconds: float,
        progress_callback: Optional[object] = None,
        context_prompt: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None
    ) -> STTResult:
        # Simulate slight processing delay
        await asyncio.sleep(1.0)
        
        duration = max(300.0, duration_seconds)
        utterances: List[STTUtterance] = []
        
        # Distribute script across time
        step = duration / (len(self.script_templates) + 2)
        cur_time = 30.0  # start after 30s
        
        speaker_totals = {
            "speaker_0": {"dur": 0.0, "count": 0, "sample": (45.0, 6.0)},
            "speaker_1": {"dur": 0.0, "count": 0, "sample": (75.0, 5.5)},
            "speaker_2": {"dur": 0.0, "count": 0, "sample": (120.0, 5.0)},
            "speaker_3": {"dur": 0.0, "count": 0, "sample": (210.0, 4.5)},
            "speaker_4": {"dur": 0.0, "count": 0, "sample": (90.0, 6.0)},
        }

        for spk, text in self.script_templates:
            dur = max(3.0, min(12.0, len(text) * 0.08))
            start_t = cur_time
            end_t = cur_time + dur
            
            utterances.append(STTUtterance(
                speaker_tag=spk,
                start_time=round(start_t, 2),
                end_time=round(end_t, 2),
                text=text,
                confidence=0.96
            ))
            
            speaker_totals[spk]["dur"] += dur
            speaker_totals[spk]["count"] += 1
            cur_time += dur + random.uniform(8.0, 25.0)

        speakers: List[STTSpeaker] = []
        for spk_tag, data in speaker_totals.items():
            speakers.append(STTSpeaker(
                speaker_tag=spk_tag,
                total_speech_seconds=round(data["dur"], 1),
                utterance_count=data["count"],
                sample_start_time=data["sample"][0],
                sample_duration=data["sample"][1]
            ))

        speakers.sort(key=lambda s: s.total_speech_seconds, reverse=True)

        return STTResult(
            utterances=utterances,
            speakers=speakers,
            provider_name="mock"
        )
