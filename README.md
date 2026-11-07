# TalentLens

TalentLens is a Flask and SQLite recruitment assessment application with recruiter accounts, candidate invitations, adaptive multiple-choice questions, section-level knowledge profiles, and assessment reports.

## Features

- Recruiter registration, sign-in, and company-scoped assessment dashboard
- Four-step assessment builder with editable, duplicable, removable, and reorderable sections
- Predefined section templates plus custom section names and topics
- Independent question count, duration, and difficulty mode for each section
- Section-scoped adaptive question difficulty and concept selection
- Candidate invitation links and server-side overall assessment timer
- Candidate progress palette and section navigation indicators; questions run sequentially
- Section and concept performance in the final report
- Free practice with an arbitrary topic
- Groq-backed AI question generation
- CSRF protection, hashed passwords, and question-specific duplicate-submission checks

The current question engine supports single-answer MCQs. Candidates complete questions sequentially within sections; section duration values contribute to the overall server-side time limit, but separate per-section timers, revisiting earlier questions, marking for review, section switching, multiple-select questions, and code execution are not supported. Coding topics can be assessed as AI-generated MCQs, but TalentLens does not evaluate submitted code.

## Run locally on Windows

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Add your GROQ_API_KEY and set a strong SECRET_KEY in .env
python app.py
```

Open <http://127.0.0.1:5000>.

Environment variables:

- `SECRET_KEY`: Flask session signing key; replace the development value.
- `GROQ_API_KEY`: Groq API key used by the existing question generator.
- `GROQ_MODEL`: optional model override (defaults to `openai/gpt-oss-20b`).
- `FLASK_DEBUG`: set to `1` only for local development.
- `DATABASE_URL`: optional SQLAlchemy database URI; defaults to the local SQLite database.

## SQLite schema upgrade

On startup, TalentLens calls `db.create_all()` to add the new `assessment_section` table, then applies additive `ALTER TABLE` statements for the new assessment description, category, and candidate-instructions fields. Existing users, assessments, and attempts are preserved. Existing single-topic assessments have no section rows and continue to run as a virtual single section using their original topic and totals.

Before deploying an update, stop the app and make a backup of the database file under `instance/` (or the file configured by `DATABASE_URL`). Start the updated app once to apply the schema additions, then verify `/health` and the recruiter dashboard. The automatic upgrade is for SQLite; a different database backend needs its own reviewed migration before deployment.

## Tests

Install pytest if it is not already available, then run:

```powershell
python -m pip install pytest
python -m pytest -q
```

The integration tests use a temporary in-memory SQLite database and mock Groq question generation. They cover saved sections, invitation and candidate flow, section-specific generation, reports, stale duplicate submissions, and legacy single-topic compatibility. They do not verify live Groq credentials or browser layout.

For production, set `FLASK_DEBUG=0`, use a strong secret, HTTPS, and a production WSGI server. Assessment reports are evidence for recruiter review, not hiring decisions.
