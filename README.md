# מוניטור גן הילדים (Kindergarten Monitor) 🧒🧸🎧

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

מערכת Full-Stack מתקדמת לניתוח פדגוגי, זיהוי אירועי מצוקה ובכי, תמלול מסונכרן והפקת דוחות בעברית מתוך הקלטות שמע של יום שלם בגן ילדים (קבצים של 5–10 שעות, עד 1GB+).

---

## ✨ יכולות מרכזיות

1. **תמיכה בקבצי שמע ארוכים וכבדים (~1GB / 5-10 שעות)**:
   - טעינה ישירה מנתיב מקומי במחשב (Local Path) או העלאה בדפדפן.
   - מיטוב ודחיסה באמצעות FFmpeg ל-16kHz מונו (חיסכון של כ-65% בנפח ללא פגיעה בדיוק הדיבור).
   - חלוקה אוטומטית למקטעים (Chunking) לקבצים החורגים ממגבלות ספקי STT.
   - הזרמת שמע בפרוטוקול HTTP 206 Partial Content להאזנה מיידית ללא צורך בהורדת הקובץ במלואו לזיכרון הדפדפן.

2. **זיהוי דיבור והפרדת דוברים (STT & Diarization)**:
   - **Gladia (v2)**: מודל מוביל בדיוק בעברית בסביבות רועשות ומרובות דוברים.
   - **Deepgram (Nova-3)**: חלופה מהירה וחסכונית.
   - **OpenAI-Compatible / OpenRouter STT**: תמיכה במגוון מודלי תמלול פתוחים ומסחריים.
   - **Mock STT מובנה**: מאפשר בדיקה והרצה מלאה של המערכת ללא צורך במפתחות API או צריכת קרדיטים.

3. **שלב זיהוי קולות אינטראקטיבי (Human-in-the-Loop Voice Tagging)**:
   - הפקת דגימות קול מבודדות (5–8 שניות) של כל דובר עיקרי שזוהה.
   - ההורה מאזין לדגימות בדפדפן, משייך תפקידים ושמות (גננת, סייעת, ילדים), ומסמן מי מתוכם הוא **הילד במוקד**.
   - הזנת שאלות והנחיות ממוקדות לדוח (לדוגמה: בדיקת יחס בארוחות, בכי בחצר, או התמודדות עם תסכול).

4. **שכבה אקוסטית וזיהוי בכי מולטימודלי (Acoustic & Multimodal Cry Detection)**:
   - ניתוח עוצמת קול (RMS Loudness) וזיהוי תדרי בכי מובהקים (1.5kHz–4kHz).
   - אימות אירועי מצוקה והתנהגות הצוות באמצעות מודלי Audio LLM (למשל `gemini-2.5-flash`).

5. **דוח פדגוגי מקיף בעברית (LLM Pedagogical Report)**:
   - תקציר מנהלים ותובנות מרכזיות.
   - מענה ישיר וממוקד לשאלות ההורה.
   - ציר זמן שגרת היום (מפגש בוקר, פעילות חצר, ארוחות, שנת צהריים).
   - פרופיל רגשי וחברתי של הילד (אירועי בכי, אופן ההרגעה וקשרים עם חברים).
   - הערכת התנהלות הצוות (חום, טון דיבור, השגחה וגבולות).
   - נורות אזהרה ואירועים חריגים עם כפתורי "נגן עכשיו" לקפיצה מיידית לרגע המדויק.

6. **עוזר אישי אינטראקטיבי ונגן שמע מסונכרן**:
   - צ'אט סוכן (Agentic Chat) עם כלים מובנים לחיפוש בתמלול, שליפת אירועים ושליטה על הנגן.
   - נגן שמע צף עם שליטה במהירות נגינה (1x, 1.25x, 1.5x, 2x), חותמות זמן וקפיצה מיידית.
   - תמלול אינטראקטיבי עם חיפוש חופשי בעברית וסינון לפי דוברים.

---

## 🚀 הוראות התקנה והפעלה מהירה

### אפשרות א': הרצה מקומית עם Python (מומלץ למפתחים)

#### 1. דרישות קדם
- **Python 3.10 ומעלה**
- **FFmpeg** (אם אינו מותקן במערכת, המערכת משתמשת אוטומטית ב-`static-ffmpeg`)

#### 2. שכפול הפרויקט והתקנת תלויות
```bash
git clone https://github.com/Bucknot/kindergarten-monitor.git
cd kindergarten-monitor

# יצירת סביבה וירטואלית והפעלתה
python3 -m venv .venv
source .venv/bin/activate   # ב-Windows: .venv\Scripts\activate

# התקנת התלויות
pip install -r requirements.txt
```

#### 3. הגדרת משתני סביבה
העתק את קובץ הדוגמה לקובץ `.env`:
```bash
cp .env.example .env
```
ערוך את `.env` והזן את המפתחות שברצונך להשתמש בהם (או השאר על `mock` לבדיקה חופשית):
```env
STT_PROVIDER=mock          # mock | gladia | deepgram | openai_compatible
LLM_PROVIDER=mock          # mock | openrouter | openai | anthropic | gemini
```

#### 4. הפעלת השרת
```bash
python run.py
```
פתח את הדפדפן בכתובת: **[http://localhost:8000](http://localhost:8000)**

---

### אפשרות ב': הרצה עם Docker

```bash
cp .env.example .env
docker compose up --build
```
המערכת תהיה זמינה מיידית בכתובת: **[http://localhost:8000](http://localhost:8000)**. הנתונים יישמרו בתיקיית `storage/` המקומית.

---

## 🧪 הרצת בדיקות אוטומטיות (Tests)

כל הבדיקות מתוכננות לרוץ באופן עצמאי ומבודד:
```bash
python3 -m pytest
```

---

## 📁 מבנה הפרויקט

```
kindergarten-monitor/
├── run.py                          # שרת הפיתוח (uvicorn launcher)
├── .env.example                    # תבנית משתני סביבה מתועדת
├── Dockerfile                      # קובץ בניית קונטיינר Docker
├── docker-compose.yml              # קובץ שירות Docker Compose
├── storage/                        # תיקיית מידע מקומית (uploads, cache, snippets, db)
├── backend/app/
│   ├── config.py                   # הגדרות מערכת ואימות נתיבים
│   ├── database.py                 # מנוע SQLite אסינכרוני (SQLAlchemy)
│   ├── models.py                   # טבלאות המודל בבסיס הנתונים
│   ├── schemas.py                  # Pydantic Schemas
│   ├── api/                        # נתיבי ה-API (sessions, audio, speakers, transcripts, reports, chat)
│   └── services/
│       ├── audio_service.py        # דחיסה, חיתוך, בדיקת מטא-דאטה עם ffmpeg
│       ├── cache_service.py        # מנגנון קאשינג מהיר של קבצי שמע ותמלול
│       ├── acoustic/               # ניתוח אקוסטיקה ועוצמות בכי
│       ├── stt/                    # מודולי תמלול (Gladia, Deepgram, Mock)
│       └── llm/                    # מודולי הפקת דוחות, סוכן צ'אט ו-Audio LLM
├── frontend/
│   ├── index.html                  # ממשק משתמש RTL בעברית
│   ├── css/styles.css              # עיצוב מודרני עם Tailwind CSS
│   └── js/                         # לוגיקת הממשק (שמע, תיוג דוברים, דוחות, צ'אט)
└── tests/                          # בדיקות יחידה ואינטגרציה
```

---

## 🔒 אבטחה ופרטיות

- קובצי השמע, התמלולים, מסדי הנתונים ודגימות הקול נשמרים בתיקיית `storage/` המוגדרת ב-`.gitignore`.
- מפתחות API וסודות אינם נשמרים ב-Git ומוגדרים אך ורק דרך קובץ `.env` המקומי.
- המערכת אינה מעבירה שמע לגורם שלישי למעט ספקי ה-STT/LLM שנבחרו ישירות על ידי המשתמש.

---

## 📄 רישיון

פרויקט זה מופץ תחת רישיון [MIT](LICENSE).
