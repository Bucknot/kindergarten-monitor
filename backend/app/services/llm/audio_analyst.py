import os
import re
import json
import base64
import logging
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from backend.app.config import settings
from backend.app.services.acoustic.acoustic_service import DetectedAudioEvent

logger = logging.getLogger(__name__)


class AudioAnalystService:
    """
    Audio-native LLM analyst using multimodal audio models (Gemini 2.5 Flash).
    Listens directly to raw audio clips to detect non-speech events (crying, screaming,
    soothing, tantrums, adult harshness) that STT models discard.
    """

    def __init__(self):
        self.model = settings.AUDIO_LLM_MODEL
        self.base_url = settings.OPENROUTER_BASE_URL.rstrip("/")

    async def analyze_candidate_window(
        self,
        audio_path: str,
        start_seconds: float,
        duration_seconds: float,
        target_child_name: Optional[str] = None,
        focus_prompt: Optional[str] = None
    ) -> List[DetectedAudioEvent]:
        """
        Extracts a compact 32kbps mono audio clip and sends it to the audio-native LLM.
        Returns detailed detected acoustic events with absolute recording timestamps.
        """
        api_key = settings.OPENROUTER_API_KEY or settings.GEMINI_API_KEY
        if not api_key:
            logger.info("No OpenRouter/Gemini API key configured; skipping audio LLM analysis.")
            return []

        # 1. Extract 32kbps mono 16kHz MP3 clip
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_clip_path = tmp.name

        try:
            cmd = [
                settings.FFMPEG_PATH, "-y", "-nostdin", "-loglevel", "error",
                "-ss", str(start_seconds), "-t", str(duration_seconds),
                "-i", audio_path,
                "-ac", "1", "-ar", "16000", "-b:a", "32k",
                tmp_clip_path
            ]
            await asyncio.to_thread(subprocess.run, cmd, check=True)

            with open(tmp_clip_path, "rb") as f:
                b64_audio = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Error extracting audio clip for LLM analysis: {e}")
            return []
        finally:
            if os.path.exists(tmp_clip_path):
                try:
                    os.remove(tmp_clip_path)
                except Exception:
                    pass

        # 2. Build multimodal prompt
        child_context = f"הילד במוקד הוא: {target_child_name}." if target_child_name else "המקליט נענד על גוף אחד הילדים (קרוב מאוד למיקרופון)."
        focus_context = f"שאלת מוקד של ההורים: {focus_prompt}" if focus_prompt else ""

        system_prompt = (
            "You are an expert acoustic child psychologist and Hebrew audio analyst analyzing kindergarten recordings. "
            "You listen directly to raw audio to detect emotional events, crying, screaming, tantrums, distress, and adult reactions. "
            "STT models often discard non-speech crying; your job is to identify what really happened. Output strictly in valid JSON format."
        )

        user_prompt = f"""האזן היטב לקטע השמע המצורף (עברית).
{child_context}
{focus_context}

זהה כל אירוע אקוסטי ורגשי משמעותי, כולל קולות שאינם דיבור (בכי, צעקות, צווחות, צחוק, ניסיונות הרגעה, דיבור תקיף/רך).
החזר אך ורק מבנה JSON תקין ומדויק:
{{
  "has_acoustic_events": true,
  "events": [
    {{
      "offset_start": 0.0,
      "offset_end": 15.0,
      "type": "crying|screaming|shouting|laughing|soothing|conflict",
      "intensity": "low|medium|high",
      "who": "ילד קרוב למיקרופון / ילד אחר / איש צוות",
      "description": "תיאור מדויק בעברית של מה שנשמע בקול (למשל: בכי חזק ומצוקה, יבבות)",
      "adult_response": "כיצד הגיב איש הצוות (הרגעה בסבלנות, הצעת חותמת/חיבוק, התעלמות, נזיפה וכו')",
      "adult_latency_seconds": 25,
      "quotes": ["ציטוטים רלוונטיים שנאמרו בעברית"]
    }}
  ],
  "summary": "סיכום תמציתי של המתרחש בחלון הזמן הזה"
}}
שים לב: offset_start ו-offset_end נמדדים בשניות מתחילת קטע השמע הנוכחי (0 עד {int(duration_seconds)})."""

        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "input_audio", "input_audio": {"data": b64_audio, "format": "mp3"}}
                    ]
                }
            ],
            "max_tokens": 1500
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://kindergarten-monitor.local",
            "X-Title": "Kindergarten Monitor",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if res.status_code != 200:
                    logger.warning(f"Audio LLM API error ({res.status_code}): {res.text[:200]}")
                    return []

                data = res.json()
                content = data["choices"][0]["message"]["content"]
                parsed = self._safe_parse_json(content)
                if not parsed or not parsed.get("has_acoustic_events"):
                    return []

                detected_events: List[DetectedAudioEvent] = []
                for ev in parsed.get("events", []):
                    off_st = float(ev.get("offset_start", 0.0))
                    off_et = float(ev.get("offset_end", off_st + 5.0))
                    # Convert to absolute timestamps
                    abs_st = round(start_seconds + off_st, 1)
                    abs_et = round(start_seconds + off_et, 1)

                    detected_events.append(DetectedAudioEvent(
                        event_type=ev.get("type", "crying"),
                        start_time=abs_st,
                        end_time=abs_et,
                        peak_score=0.95,
                        source="gemini",
                        intensity=ev.get("intensity", "medium"),
                        description=ev.get("description"),
                        adult_response=ev.get("adult_response"),
                        quotes=ev.get("quotes", [])
                    ))

                return detected_events

        except Exception as e:
            logger.warning(f"Audio LLM analysis call failed: {e}")
            return []

    async def listen_to_clip(
        self,
        audio_path: str,
        start_seconds: float,
        end_seconds: float,
        question: str
    ) -> str:
        """
        Direct audio listening tool for the Chat Agent.
        Extracts audio clip and asks Gemini to answer a parent's question based on real acoustics.
        """
        api_key = settings.OPENROUTER_API_KEY or settings.GEMINI_API_KEY
        if not api_key:
            return "מפתח OpenRouter/Gemini אינו מוגדר, לא ניתן להאזין ישירות לשמע."

        duration = max(5.0, min(120.0, end_seconds - start_seconds))
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_clip_path = tmp.name

        try:
            cmd = [
                settings.FFMPEG_PATH, "-y", "-nostdin", "-loglevel", "error",
                "-ss", str(start_seconds), "-t", str(duration),
                "-i", audio_path,
                "-ac", "1", "-ar", "16000", "-b:a", "32k",
                tmp_clip_path
            ]
            await asyncio.to_thread(subprocess.run, cmd, check=True)

            with open(tmp_clip_path, "rb") as f:
                b64_audio = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return f"שגיאה בחיתוך קטע השמע: {e}"
        finally:
            if os.path.exists(tmp_clip_path):
                try:
                    os.remove(tmp_clip_path)
                except Exception:
                    pass

        prompt = f"""האזן לקטע השמע המצורף מהגן וענה על שאלת ההורה בעברית בהירה, אובייקטיבית ואמינה:
שאלת ההורה: "{question}"
שים לב לקולות הדיבור, טון הדיבור, רעשי רקע, בכי, צחוק או מצוקה. תאר בדיוק מה שומעים."""

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "input_audio", "input_audio": {"data": b64_audio, "format": "mp3"}}
                    ]
                }
            ],
            "max_tokens": 800
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://kindergarten-monitor.local",
            "X-Title": "Kindergarten Monitor",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"]
                return f"שגיאה בתקשורת עם מודל השמע ({res.status_code})"
        except Exception as e:
            return f"שגיאה בהאזנה לקטע: {e}"

    def _safe_parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        text = content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        elif "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1].strip()

        try:
            return json.loads(text)
        except Exception:
            # Simple quote repair
            if text.count('"') % 2 != 0:
                text += '"'
            try:
                return json.loads(text + "}")
            except Exception:
                return None


audio_analyst = AudioAnalystService()
