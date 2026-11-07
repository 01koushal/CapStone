import json
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import app
from db_models import Assessment, AssessmentSection, Attempt
from extensions import db
from models import Question


@pytest.fixture
def client(tmp_path):
    original_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.session.remove()
        db._app_engines[app][None] = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.create_all()
    yield app.test_client()
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db._app_engines[app][None].dispose()
        db._app_engines[app].clear()
    app.config.update(TESTING=False, WTF_CSRF_ENABLED=True,
                      SQLALCHEMY_DATABASE_URI=original_uri)


def register(client):
    response = client.post("/register", data={
        "company": "Example Hiring", "name": "Riley Recruiter",
        "email": "riley@example.test", "password": "secure-pass-123",
    }, follow_redirects=True)
    assert response.status_code == 200


def posted_question_id(response):
    match = re.search(rb'name="question_id" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def test_multisection_assessment_persists_adapts_and_reports(client, monkeypatch):
    import app as app_module

    register(client)
    assert b"Welcome, Riley Recruiter" in client.get("/dashboard").data
    assert b"Add a section" in client.get("/assessments/new").data
    client.get("/logout")
    assert client.post("/login", data={"email": "riley@example.test", "password": "secure-pass-123"}).status_code == 302
    sections = [
        {"name": "Aptitude", "topics": ["Quantitative Aptitude", "Reasoning"],
         "question_count": 1, "duration_minutes": 3, "difficulty_mode": "adaptive", "question_types": ["mcq"]},
        {"name": "DSA", "topics": ["Trees", "Graphs"], "question_count": 1,
         "duration_minutes": 4, "difficulty_mode": "hard", "question_types": ["mcq"]},
    ]
    response = client.post("/assessments/new", data={
        "title": "Developer Screen", "description": "A multi-section screen",
        "category": "Software Engineering", "instructions": "Answer each item.",
        "sections_json": json.dumps(sections),
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        assessment = Assessment.query.filter_by(title="Developer Screen").one()
        assert [(s.name, s.question_count, s.duration_minutes) for s in assessment.sections] == [
            ("Aptitude", 1, 3), ("DSA", 1, 4)]
        assert assessment.question_count == 2
        assert assessment.duration_minutes == 7
        invite_url = f"/invite/{assessment.token}"

    calls = []
    def fake_question(topic, concept, difficulty, previous_questions=None, previous_answer=None):
        calls.append((topic, concept, difficulty, previous_questions))
        return Question(id=f"q{len(calls)}", topic=topic, concept=concept, difficulty=difficulty,
                        question=f"Question in {concept}", options=["A", "B", "C", "D"],
                        correct_answer="A", explanation="Verified explanation.")
    monkeypatch.setattr(app_module, "generate_question", fake_question)

    assert client.get(invite_url).status_code == 200
    started = client.post(invite_url, data={"name": "Candidate One", "email": ""})
    assert started.status_code == 302
    first = client.get("/take")
    assert b"Aptitude" in first.data
    first_id = posted_question_id(first)
    client.post("/take", data={"answer": "A", "question_id": first_id})
    second = client.get("/take")
    assert b"DSA" in second.data
    assert len(calls) == 2
    assert "Trees" in calls[1][0] and "Graphs" in calls[1][0]
    assert calls[1][2] == 3
    second_id = posted_question_id(second)
    client.post("/take", data={"answer": "A", "question_id": first_id})
    still_second = client.get("/take")
    assert posted_question_id(still_second) == second_id
    completed = client.post("/take", data={"answer": "A", "question_id": second_id}, follow_redirects=True)
    assert completed.status_code == 200
    assert b"Section performance" in completed.data
    assert b"Aptitude" in completed.data and b"DSA" in completed.data
    with app.app_context():
        attempt = Attempt.query.one()
        profile = json.loads(attempt.profile_json)
        assert any(key.startswith("section:0:Quantitative Aptitude") for key in profile)
        assert any(key.startswith("section:1:") for key in profile)


def test_single_topic_legacy_creation_still_works(client, monkeypatch):
    import app as app_module

    register(client)
    response = client.post("/assessments/new", data={
        "title": "Legacy Screen", "topic": "Python", "question_count": 1, "duration": 5,
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assessment = Assessment.query.filter_by(title="Legacy Screen").one()
        assert AssessmentSection.query.filter_by(assessment_id=assessment.id).count() == 0
        invite_url = f"/invite/{assessment.token}"

    monkeypatch.setattr(app_module, "generate_question", lambda topic, concept, difficulty,
                        previous_questions=None, previous_answer=None: Question(
        id="legacy", topic=topic, concept=concept, difficulty=difficulty,
        question="Legacy question", options=["A", "B", "C", "D"],
        correct_answer="A", explanation="Legacy explanation"))
    client.post(invite_url, data={"name": "Candidate Legacy"})
    question = client.get("/take")
    assert b"Python" in question.data
    result = client.post("/take", data={"answer": "A", "question_id": posted_question_id(question)}, follow_redirects=True)
    assert b"100" in result.data and b"Section performance" in result.data


def test_free_practice_still_completes(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "generate_question", lambda topic, concept, difficulty,
                        previous_questions=None, previous_answer=None: Question(
        id="practice", topic=topic, concept=concept, difficulty=difficulty,
        question="Practice question", options=["A", "B", "C", "D"],
        correct_answer="B", explanation="Practice explanation"))
    assert client.get("/free-test").status_code == 200
    started = client.post("/free-test", data={"name": "Learner", "topic": "SQL",
        "question_count": 1, "duration": 5})
    assert started.status_code == 302
    question = client.get("/take")
    assert b"Practice question" in question.data
    result = client.post("/take", data={"answer": "B", "question_id": posted_question_id(question)},
                         follow_redirects=True)
    assert b"100" in result.data and b"SQL" in result.data
