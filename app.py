
import json
import os
import secrets

from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    abort,
)

from flask_login import (
    login_user,
    logout_user,
    login_required,
    current_user,
)

from sqlalchemy import inspect, text

from config import Config
from extensions import db, login_manager, csrf

from db_models import (
    User,
    Assessment,
    AssessmentSection,
    Attempt,
)

from models import StudentProfile, ConceptKnowledge

from adaptive import choose_difficulty, choose_next_concept

from knowledge import update_knowledge, normalize_knowledge

from ai import generate_question


app = Flask(__name__)

app.config.from_object(Config)

db.init_app(app)
login_manager.init_app(app)
csrf.init_app(app)


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --------------------------------------------------
# KNOWLEDGE PROFILE
# --------------------------------------------------

def profile_from_json(name, raw):

    data = json.loads(raw or "{}")

    profile = StudentProfile(name=name)

    for key, value in data.items():

        knowledge = ConceptKnowledge(**value)

        normalize_knowledge(knowledge)

        profile.knowledge[key] = knowledge

    return profile


def profile_to_json(profile):

    return json.dumps({
        key: vars(value)
        for key, value in profile.knowledge.items()
    })


# --------------------------------------------------
# ATTEMPT MANAGEMENT
# --------------------------------------------------

def current_attempt():

    attempt_id = session.get("attempt_id")

    return db.session.get(Attempt, attempt_id) if attempt_id else None


def configured_sections(assessment):

    """
    Return configured sections.

    Existing single-topic assessments receive
    a virtual section for backward compatibility.
    """

    if assessment.sections:
        return assessment.sections

    return [
        dict(
            id=None,
            name=assessment.topic,
            description="",
            display_order=0,
            question_count=assessment.question_count,
            duration_minutes=assessment.duration_minutes,
            difficulty_mode="adaptive",
            topics=[assessment.topic],
            question_types=["mcq"],
        )
    ]


def section_value(section, key):

    if isinstance(section, dict):
        return section.get(key)

    return getattr(section, key)


def active_section(assessment, history):

    sections = configured_sections(assessment)

    answered = len(history)

    for section in sections:

        count = section_value(section, "question_count")

        if answered < count:
            return section

        answered -= count

    return sections[-1] if sections else None


# --------------------------------------------------
# SECTION-SPECIFIC KNOWLEDGE
# --------------------------------------------------

def _scoped_profile(attempt, section):

    profile = profile_from_json(
        attempt.candidate_name,
        attempt.profile_json
    )

    prefix = (
        f"section:{section_value(section, 'display_order')}:"
    )

    scoped = StudentProfile(name=attempt.candidate_name)

    scoped.knowledge = {
        key[len(prefix):]: value
        for key, value in profile.knowledge.items()
        if key.startswith(prefix)
    }

    return scoped


# --------------------------------------------------
# ADAPTIVE QUESTION GENERATION
# --------------------------------------------------

def get_or_create_question(attempt):

    # Reuse the currently active question.
    if attempt.current_question_json:

        return json.loads(attempt.current_question_json)

    history = json.loads(attempt.history_json or "[]")

    section = active_section(
        attempt.assessment,
        history
    )

    if section is None:

        raise ValueError(
            "This assessment has no sections configured."
        )

    scoped = _scoped_profile(attempt, section)

    topics = section_value(section, "topics")

    topics = [
        item.strip()
        for item in topics
        if isinstance(item, str) and item.strip()
    ]

    topic_scope = ", ".join(topics) or section_value(
        section, "name"
    )

    concept = choose_next_concept(
        scoped,
        topics,
        default_topic=section_value(section, "name")
    ) if topics else section_value(section, "name")

    mode = section_value(section, "difficulty_mode")

    difficulty = {
        "easy": 1,
        "medium": 2,
        "hard": 3,
    }.get(
        mode,
        choose_difficulty(scoped, concept)
    )

    section_order = section_value(
        section, "display_order"
    )

    section_history = [
        item
        for item in history
        if item.get("section_order") == section_order
    ]

    # Generate the next AI question.
    question = generate_question(
        topic_scope,
        concept,
        difficulty,
        [
            item["question"]
            for item in section_history
        ],
        section_history[-1] if section_history else None
    )

    payload = {
        "id": question.id,
        "topic": section_value(section, "name"),
        "concept": concept,
        "difficulty": question.difficulty,
        "question": question.question,
        "options": question.options,
        "correct_answer": question.correct_answer,
        "explanation": question.explanation,
        "section_id": section_value(section, "id"),
        "section_name": section_value(section, "name"),
        "section_order": section_order,
        "section_question_number": len(section_history) + 1,
    }

    attempt.current_question_json = json.dumps(payload)

    db.session.commit()

    return payload


# --------------------------------------------------
# COMPLETE ATTEMPT
# --------------------------------------------------

def finish_attempt(attempt):

    history = json.loads(attempt.history_json or "[]")

    attempt.status = "completed"

    attempt.completed_at = (
        datetime.now(timezone.utc).replace(tzinfo=None)
    )

    attempt.score = (
        round(
            sum(1 for item in history if item["correct"])
            / len(history) * 100,
            1
        )
        if history else 0
    )

    db.session.commit()


# --------------------------------------------------
# PUBLIC HOMEPAGE
# --------------------------------------------------

@app.route("/")
def index():

    return render_template("index.html")


# --------------------------------------------------
# REGISTRATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        company = request.form.get("company", "").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not all([company, name, email, password]) or len(password) < 8:

            flash(
                "Complete all fields. Password must be at least 8 characters.",
                "error"
            )

        elif User.query.filter_by(email=email).first():

            flash(
                "An account with that email already exists.",
                "error"
            )

        else:

            user = User(
                company=company,
                name=name,
                email=email
            )

            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            login_user(user)

            return redirect(url_for("dashboard"))

    return render_template(
        "auth.html",
        mode="Create account"
    )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        user = User.query.filter_by(
            email=request.form.get("email", "").strip().lower()
        ).first()

        if user and user.check_password(
            request.form.get("password", "")
        ):

            login_user(user)

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template(
        "auth.html",
        mode="Sign in"
    )


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(url_for("index"))


# --------------------------------------------------
# RECRUITER DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    assessments = (
        Assessment.query
        .filter_by(recruiter_id=current_user.id)
        .order_by(Assessment.created_at.desc())
        .all()
    )

    return render_template(
        "dashboard.html",
        assessments=assessments
    )


# --------------------------------------------------
# CREATE ASSESSMENT
# --------------------------------------------------

@app.route("/assessments/new", methods=["GET", "POST"])
@login_required
def new_assessment():

    if request.method == "POST":

        title = request.form.get("title", "").strip()

        description = request.form.get(
            "description", ""
        ).strip()

        category = request.form.get(
            "category", "General"
        ).strip() or "General"

        instructions = request.form.get(
            "instructions", ""
        ).strip()

        raw_sections = request.form.get(
            "sections_json", ""
        ).strip()

        try:

            if raw_sections:

                sections = json.loads(raw_sections)

                if not isinstance(sections, list) or not 1 <= len(sections) <= 12:

                    raise ValueError(
                        "Add between 1 and 12 sections."
                    )

                normalized = []

                total_count = 0
                total_duration = 0

                for order, item in enumerate(sections):

                    if not isinstance(item, dict):

                        raise ValueError(
                            "Invalid section configuration."
                        )

                    name = str(
                        item.get("name", "")
                    ).strip()[:140]

                    topics = item.get("topics", [])

                    if isinstance(topics, str):

                        topics = [
                            x.strip()
                            for x in topics.split(",")
                        ]

                    topics = list(dict.fromkeys(
                        x.strip()[:100]
                        for x in topics
                        if isinstance(x, str) and x.strip()
                    ))

                    count = int(
                        item.get("question_count", 0)
                    )

                    duration = int(
                        item.get("duration_minutes", 0)
                    )

                    difficulty = str(
                        item.get("difficulty_mode", "adaptive")
                    ).lower()

                    if (
                        not name
                        or not topics
                        or not 1 <= count <= 30
                        or not 1 <= duration <= 240
                    ):

                        raise ValueError(
                            "Each section needs a name, topics, "
                            "1-30 questions, and 1-240 minutes."
                        )

                    if difficulty not in (
                        "adaptive",
                        "easy",
                        "medium",
                        "hard"
                    ):

                        raise ValueError(
                            "Choose a valid difficulty for every section."
                        )

                    types = item.get(
                        "question_types", ["mcq"]
                    )

                    if (
                        not isinstance(types, list)
                        or not types
                        or any(value != "mcq" for value in types)
                    ):

                        raise ValueError(
                            "Only single-answer multiple-choice "
                            "questions are currently supported."
                        )

                    normalized.append({

                        "name": name,

                        "description": str(
                            item.get("description", "")
                        )[:500],

                        "display_order": order,

                        "question_count": count,

                        "duration_minutes": duration,

                        "difficulty_mode": difficulty,

                        "topics": topics,

                        "question_types": ["mcq"],

                    })

                    total_count += count
                    total_duration += duration

                if total_count > 60 or total_duration > 240:

                    raise ValueError(
                        "An assessment can contain at most "
                        "60 questions and 240 minutes in total."
                    )

                count = total_count
                duration = total_duration

                topic = ", ".join(dict.fromkeys(
                    topic
                    for item in normalized
                    for topic in item["topics"]
                ))[:300]

            else:

                topic = request.form.get(
                    "topic", ""
                ).strip()

                count = max(
                    1,
                    min(
                        30,
                        int(request.form.get("question_count", 10))
                    )
                )

                duration = max(
                    5,
                    min(
                        240,
                        int(request.form.get("duration", 30))
                    )
                )

                normalized = []

        except (
            ValueError,
            TypeError,
            json.JSONDecodeError
        ) as exc:

            flash(
                str(exc) or "Enter valid question and duration values.",
                "error"
            )

            return redirect(url_for("new_assessment"))

        if not title or not topic:

            flash(
                "Assessment title and topic are required.",
                "error"
            )

        else:

            assessment = Assessment(

                recruiter_id=current_user.id,

                title=title,

                topic=topic,

                question_count=count,

                duration_minutes=duration,

                token=secrets.token_urlsafe(24),

                kind="recruiter",

                description=description,

                category=category,

                instructions=instructions,

            )

            db.session.add(assessment)

            db.session.flush()

            for item in normalized:

                db.session.add(
                    AssessmentSection(

                        assessment_id=assessment.id,

                        name=item["name"],

                        description=item["description"],

                        display_order=item["display_order"],

                        question_count=item["question_count"],

                        duration_minutes=item["duration_minutes"],

                        difficulty_mode=item["difficulty_mode"],

                        topics_json=json.dumps(item["topics"]),

                        question_types_json=json.dumps(
                            item["question_types"]
                        ),

                    )
                )

            db.session.commit()

            flash(
                "Assessment created. Share its invitation link with candidates.",
                "success"
            )

            return redirect(url_for("dashboard"))

    return render_template("new_assessment.html")


# --------------------------------------------------
# CANDIDATE INVITATION
# --------------------------------------------------

@app.route("/invite/<token>", methods=["GET", "POST"])
def invite(token):

    assessment = Assessment.query.filter_by(
        token=token,
        kind="recruiter"
    ).first_or_404()

    if request.method == "POST":

        name = request.form.get("name", "").strip()

        email = request.form.get("email", "").strip()

        if not name:

            flash(
                "Enter your name to continue.",
                "error"
            )

        else:

            now = datetime.now(
                timezone.utc
            ).replace(tzinfo=None)

            attempt = Attempt(

                assessment=assessment,

                candidate_name=name,

                candidate_email=email,

                started_at=now,

                expires_at=now + timedelta(
                    minutes=assessment.duration_minutes
                ),

                status="in_progress",

            )

            db.session.add(attempt)

            db.session.commit()

            session["attempt_id"] = attempt.id

            return redirect(
                url_for("take_assessment")
            )

    return render_template(
        "invite.html",
        assessment=assessment
    )


# --------------------------------------------------
# TAKE ASSESSMENT
# --------------------------------------------------

@app.route("/take", methods=["GET", "POST"])
def take_assessment():

    attempt = current_attempt()

    if not attempt:

        return redirect(url_for("index"))

    if attempt.status == "completed":

        return redirect(
            url_for("report", attempt_id=attempt.id)
        )

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    if attempt.expires_at and now > attempt.expires_at:

        finish_attempt(attempt)

        return redirect(
            url_for("report", attempt_id=attempt.id)
        )

    assessment = attempt.assessment

    # ----------------------------------------------
    # ANSWER SUBMISSION
    # ----------------------------------------------

    if request.method == "POST":

        q = json.loads(
            attempt.current_question_json or "{}"
        )

        raw_answer = request.form.get(
            "answer", ""
        )

        submitted_question_id = request.form.get(
            "question_id", ""
        )

        # Verify active question.
        if (
            not q
            or submitted_question_id != str(q.get("id", ""))
        ):

            flash(
                "That question is no longer active. "
                "Your current question is still available.",
                "error"
            )

            return redirect(
                url_for("take_assessment")
            )

        # ------------------------------------------
        # FIX: VALIDATE ANSWER INDEX
        # ------------------------------------------

        try:

            answer_index = int(raw_answer)

            options = q.get("options")

            if not isinstance(options, list):

                raise ValueError("Invalid options")

            if not 0 <= answer_index < len(options):

                raise ValueError("Invalid answer index")

            # Retrieve canonical answer from stored question.
            answer = options[answer_index]

        except (ValueError, TypeError, IndexError):

            flash(
                "Please select one of the available answers.",
                "error"
            )

            return redirect(
                url_for("take_assessment")
            )

        # ------------------------------------------
        # CHECK CORRECT ANSWER
        # ------------------------------------------

        correct = (
            str(answer).strip().casefold()
            == str(q["correct_answer"]).strip().casefold()
        )

        # ------------------------------------------
        # UPDATE KNOWLEDGE PROFILE
        # ------------------------------------------

        profile = profile_from_json(
            attempt.candidate_name,
            attempt.profile_json
        )

        update_knowledge(
            profile,
            f"section:{q.get('section_order', 0)}:{q['concept']}",
            correct
        )

        # ------------------------------------------
        # SAVE ANSWER HISTORY
        # ------------------------------------------

        history = json.loads(
            attempt.history_json or "[]"
        )

        history.append({

            "question": q["question"],

            "concept": q["concept"],

            "difficulty": q["difficulty"],

            "student_answer": answer,

            "correct_answer": q["correct_answer"],

            "correct": correct,

            "explanation": q["explanation"],

            "section_id": q.get("section_id"),

            "section_name": q.get(
                "section_name",
                assessment.topic
            ),

            "section_order": q.get(
                "section_order", 0
            ),

        })

        attempt.profile_json = profile_to_json(
            profile
        )

        attempt.history_json = json.dumps(history)

        attempt.question_number += 1

        attempt.current_question_json = ""

        db.session.commit()

        # ------------------------------------------
        # FINISH OR CONTINUE
        # ------------------------------------------

        if attempt.question_number >= assessment.question_count:

            finish_attempt(attempt)

        if attempt.status == "completed":

            return redirect(
                url_for("report", attempt_id=attempt.id)
            )

        return redirect(
            url_for("take_assessment")
        )

    # ----------------------------------------------
    # GET NEXT QUESTION
    # ----------------------------------------------

    try:

        q = get_or_create_question(attempt)

    except Exception as exc:

        app.logger.exception(
            "Question generation failed"
        )

        flash(
            f"Could not generate the next question: {exc}. "
            "Your previous answers are saved; retry below.",
            "error"
        )

        q = None

    # ----------------------------------------------
    # REMAINING TIME
    # ----------------------------------------------

    remaining = (
        max(
            0,
            int(
                (
                    attempt.expires_at
                    - datetime.now(timezone.utc).replace(tzinfo=None)
                ).total_seconds()
            )
        )
        if attempt.expires_at
        else None
    )

    history = json.loads(
        attempt.history_json or "[]"
    )

    sections = configured_sections(assessment)

    section = (
        active_section(assessment, history)
        if q else None
    )

    section_status = []

    remaining_count = len(history)

    for item in sections:

        answered = min(
            remaining_count,
            section_value(item, "question_count")
        )

        section_status.append({

            "name": section_value(item, "name"),

            "order": section_value(item, "display_order"),

            "question_count": section_value(
                item, "question_count"
            ),

            "answered": answered,

            "active": bool(
                section
                and section_value(section, "display_order")
                == section_value(item, "display_order")
            ),

        })

        remaining_count = max(
            0,
            remaining_count - section_value(
                item, "question_count"
            )
        )

    return render_template(

        "take.html",

        attempt=attempt,

        assessment=assessment,

        q=q,

        remaining=remaining,

        sections=section_status,

        section=section,

        history=history,

    )


# --------------------------------------------------
# RETRY QUESTION GENERATION
# --------------------------------------------------

@app.route("/retry-question", methods=["POST"])
def retry_question():

    attempt = current_attempt()

    if not attempt:

        return redirect(url_for("index"))

    if attempt.status != "in_progress":

        return redirect(
            url_for("index")
        )

    attempt.current_question_json = ""

    db.session.commit()

    return redirect(
        url_for("take_assessment")
    )


# --------------------------------------------------
# CANDIDATE REPORT
# --------------------------------------------------

@app.route("/report/<int:attempt_id>")
def report(attempt_id):

    attempt = db.session.get(
        Attempt,
        attempt_id
    )

    if not attempt:

        abort(404)

    if (
        attempt.status != "completed"
        and not (
            current_user.is_authenticated
            and attempt.assessment.recruiter_id == current_user.id
        )
    ):

        abort(403)

    history = json.loads(
        attempt.history_json or "[]"
    )

    profile = profile_from_json(
        attempt.candidate_name,
        attempt.profile_json
    )

    mastery = {
        key.split(":", 2)[-1]: value
        for key, value in profile.knowledge.items()
    }

    strongest = (
        max(
            mastery.items(),
            key=lambda x: x[1].mastery
        )[0]
        if mastery else "—"
    )

    weakest = (
        min(
            mastery.items(),
            key=lambda x: x[1].mastery
        )[0]
        if mastery else "—"
    )

    section_reports = []

    for section in configured_sections(attempt.assessment):

        order = section_value(
            section, "display_order"
        )

        answers = [
            item
            for item in history
            if item.get("section_order", 0) == order
        ]

        right = sum(
            bool(item.get("correct"))
            for item in answers
        )

        scoped = {

            key.split(":", 2)[-1]: value

            for key, value in profile.knowledge.items()

            if key.startswith(f"section:{order}:")

        }

        section_reports.append({

            "name": section_value(section, "name"),

            "questions": section_value(
                section, "question_count"
            ),

            "answered": len(answers),

            "correct": right,

            "score": (
                round(right / len(answers) * 100)
                if answers else 0
            ),

            "mastery": scoped,

            "topics": section_value(section, "topics"),

        })

    scored_sections = [
        item
        for item in section_reports
        if item["answered"]
    ]

    strongest_section = (
        max(
            scored_sections,
            key=lambda item: item["score"]
        )["name"]
        if scored_sections else "—"
    )

    weakest_section = (
        min(
            scored_sections,
            key=lambda item: item["score"]
        )["name"]
        if scored_sections else "—"
    )

    return render_template(

        "report.html",

        attempt=attempt,

        history=history,

        mastery=mastery,

        strongest=strongest,

        weakest=weakest,

        section_reports=section_reports,

        strongest_section=strongest_section,

        weakest_section=weakest_section,

    )


# --------------------------------------------------
# FREE PRACTICE
# --------------------------------------------------

@app.route("/free-test", methods=["GET", "POST"])
def free_test():

    if request.method == "POST":

        topic = request.form.get(
            "topic", ""
        ).strip()

        name = request.form.get(
            "name", ""
        ).strip() or "Practice learner"

        try:

            count = max(
                1,
                min(
                    30,
                    int(request.form.get("question_count", 10))
                )
            )

            duration = max(
                5,
                min(
                    240,
                    int(request.form.get("duration", 30))
                )
            )

        except ValueError:

            count, duration = 10, 30

        if not topic:

            flash(
                "Enter any topic to practice.",
                "error"
            )

        else:

            assessment = Assessment(

                recruiter_id=None,

                title="Free practice",

                topic=topic,

                question_count=count,

                duration_minutes=duration,

                token=secrets.token_urlsafe(24),

                kind="practice",

            )

            db.session.add(assessment)

            db.session.flush()

            attempt = Attempt(

                assessment=assessment,

                candidate_name=name,

                started_at=datetime.now(
                    timezone.utc
                ).replace(tzinfo=None),

                expires_at=datetime.now(
                    timezone.utc
                ).replace(tzinfo=None) + timedelta(
                    minutes=duration
                ),

                status="in_progress",

            )

            db.session.add(attempt)

            db.session.commit()

            session["attempt_id"] = attempt.id

            return redirect(
                url_for("take_assessment")
            )

    return render_template("free_test.html")


# --------------------------------------------------
# RECRUITER REPORT ACCESS
# --------------------------------------------------

@app.route("/recruiter/attempt/<int:attempt_id>")
@login_required
def recruiter_attempt_report(attempt_id):

    attempt = db.session.get(
        Attempt,
        attempt_id
    )

    if (
        not attempt
        or attempt.assessment.recruiter_id != current_user.id
    ):

        abort(404)

    return redirect(
        url_for("report", attempt_id=attempt_id)
    )


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/health")
def health():

    return {"status": "ok"}


# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------

with app.app_context():

    db.create_all()

    # Safe additive SQLite schema upgrades.
    # Existing records are preserved.

    inspector = inspect(db.engine)

    if "assessment" in inspector.get_table_names():

        columns = {
            column["name"]
            for column in inspector.get_columns("assessment")
        }

        additions = (

            ("description", "TEXT NOT NULL DEFAULT ''"),

            ("category", "VARCHAR(80) NOT NULL DEFAULT 'General'"),

            ("instructions", "TEXT NOT NULL DEFAULT ''"),

        )

        for name, definition in additions:

            if name not in columns:

                db.session.execute(
                    text(
                        f"ALTER TABLE assessment ADD COLUMN "
                        f"{name} {definition}"
                    )
                )

        db.session.commit()


# --------------------------------------------------
# APPLICATION ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":

    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1"
    )
