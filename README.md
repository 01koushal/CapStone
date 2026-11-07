# TalentLens — Flask Adaptive Assessment Platform

Flask + SQLite recruitment assessments and open practice, using the adaptive/knowledge engine from the source GitHub repository:
https://github.com/01koushal/ai-driven-adaptive-assessment-system

## Features
- Recruiter registration/login and company-owned dashboard
- Create assessments with arbitrary topic, question count and total duration
- Shareable candidate invitation URL; candidate sees assessment details before starting
- AI-generated MCQs using Groq (`openai/gpt-oss-20b`)
- Adaptive selection: target the weakest concept and choose level 1/2/3 from mastery thresholds
- Knowledge updates: mastery +0.10 for correct, -0.10 for incorrect, clamped to [0, 1]; confidence = questions_seen / 10 (capped)
- Candidate reports with score, concept mastery, strongest/weakest concept and answer review
- Free practice with any user-entered topic and configurable question count/duration
- SQLite persistence, CSRF protection, password hashing, secure random invite tokens, recruiter data isolation

## Run on Windows PowerShell
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and add your GROQ_API_KEY plus a long random SECRET_KEY
python app.py
```
Open http://127.0.0.1:5000

If PowerShell blocks activation:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

The SQLite database is created automatically at first start. For production, set `FLASK_DEBUG=0`, use a strong secret, HTTPS, and a production WSGI server. The report URL is public to the candidate who has completed that attempt; recruiter access is restricted to the owning account.

\n## AI response compatibility\nThe question parser accepts difficulty as either a numeric level (1–3) or a model label such as `Medium (level 2)`. This prevents otherwise valid generated questions from failing during parsing.\n