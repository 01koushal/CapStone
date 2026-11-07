import json, os, secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from config import Config
from extensions import db, login_manager, csrf
from db_models import User, Assessment, Attempt
from models import StudentProfile, ConceptKnowledge
from adaptive import choose_difficulty, choose_next_concept
from knowledge import update_knowledge
from ai import generate_question

app=Flask(__name__)
app.config.from_object(Config)
db.init_app(app); login_manager.init_app(app); csrf.init_app(app)

@login_manager.user_loader
def load_user(user_id): return db.session.get(User,int(user_id))

def profile_from_json(name, raw):
    data=json.loads(raw or "{}")
    p=StudentProfile(name=name)
    for k,v in data.items():
        p.knowledge[k]=ConceptKnowledge(**v)
    return p

def profile_to_json(profile):
    return json.dumps({k:vars(v) for k,v in profile.knowledge.items()})

def current_attempt():
    aid=session.get("attempt_id")
    return db.session.get(Attempt,aid) if aid else None

def get_or_create_question(attempt):
    if attempt.current_question_json:
        return json.loads(attempt.current_question_json)
    profile=profile_from_json(attempt.candidate_name,attempt.profile_json)
    hist=json.loads(attempt.history_json or "[]")
    concept=choose_next_concept(profile,attempt.assessment.topic)
    difficulty=choose_difficulty(profile,concept)
    q=generate_question(attempt.assessment.topic,concept,difficulty,
        [x["question"] for x in hist],hist[-1] if hist else None)
    payload={"id":q.id,"topic":q.topic,"concept":q.concept,"difficulty":q.difficulty,
        "question":q.question,"options":q.options,"correct_answer":q.correct_answer,"explanation":q.explanation}
    attempt.current_question_json=json.dumps(payload)
    db.session.commit()
    return payload

def finish_attempt(attempt):
    hist=json.loads(attempt.history_json or "[]")
    attempt.status="completed"; attempt.completed_at=datetime.utcnow()
    attempt.score=round((sum(1 for x in hist if x["correct"])/len(hist))*100,1) if hist else 0
    db.session.commit()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        company=request.form.get("company","").strip()
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        if not all([company,name,email,password]) or len(password)<8:
            flash("Complete all fields. Password must be at least 8 characters.","error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.","error")
        else:
            u=User(company=company,name=name,email=email); u.set_password(password)
            db.session.add(u); db.session.commit(); login_user(u)
            return redirect(url_for("dashboard"))
    return render_template("auth.html",mode="Create account")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=User.query.filter_by(email=request.form.get("email","").strip().lower()).first()
        if u and u.check_password(request.form.get("password","")):
            login_user(u); return redirect(url_for("dashboard"))
        flash("Invalid email or password.","error")
    return render_template("auth.html",mode="Sign in")

@app.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    assessments=Assessment.query.filter_by(recruiter_id=current_user.id).order_by(Assessment.created_at.desc()).all()
    return render_template("dashboard.html",assessments=assessments)

@app.route("/assessments/new",methods=["GET","POST"])
@login_required
def new_assessment():
    if request.method=="POST":
        title=request.form.get("title","").strip()
        topic=request.form.get("topic","").strip()
        try:
            count=max(1,min(30,int(request.form.get("question_count",10))))
            duration=max(5,min(240,int(request.form.get("duration",30))))
        except ValueError:
            flash("Enter valid question and duration values.","error"); return redirect(url_for("new_assessment"))
        if not title or not topic:
            flash("Assessment title and topic are required.","error")
        else:
            a=Assessment(recruiter_id=current_user.id,title=title,topic=topic,question_count=count,
                duration_minutes=duration,token=secrets.token_urlsafe(24),kind="recruiter")
            db.session.add(a); db.session.commit()
            flash("Assessment created. Share its invitation link with candidates.","success")
            return redirect(url_for("dashboard"))
    return render_template("new_assessment.html")

@app.route("/invite/<token>",methods=["GET","POST"])
def invite(token):
    a=Assessment.query.filter_by(token=token,kind="recruiter").first_or_404()
    if request.method=="POST":
        name=request.form.get("name","").strip(); email=request.form.get("email","").strip()
        if not name: flash("Enter your name to continue.","error")
        else:
            attempt=Attempt(assessment=a,candidate_name=name,candidate_email=email,
                started_at=datetime.utcnow(),expires_at=datetime.utcnow()+timedelta(minutes=a.duration_minutes),status="in_progress")
            db.session.add(attempt); db.session.commit()
            session["attempt_id"]=attempt.id
            return redirect(url_for("take_assessment"))
    return render_template("invite.html",assessment=a)

@app.route("/take",methods=["GET","POST"])
def take_assessment():
    attempt=current_attempt()
    if not attempt: return redirect(url_for("index"))
    if attempt.status=="completed": return redirect(url_for("report",attempt_id=attempt.id))
    if attempt.expires_at and datetime.utcnow()>attempt.expires_at:
        finish_attempt(attempt); return redirect(url_for("report",attempt_id=attempt.id))
    assessment=attempt.assessment
    if request.method=="POST":
        q=json.loads(attempt.current_question_json or "{}")
        answer=request.form.get("answer","")
        if not q or answer not in q["options"]:
            flash("Choose one of the available answers.","error")
            return redirect(url_for("take_assessment"))
        correct=answer.strip().lower()==q["correct_answer"].strip().lower()
        profile=profile_from_json(attempt.candidate_name,attempt.profile_json)
        update_knowledge(profile,q["concept"],correct)
        history=json.loads(attempt.history_json or "[]")
        history.append({"question":q["question"],"concept":q["concept"],"difficulty":q["difficulty"],
            "student_answer":answer,"correct_answer":q["correct_answer"],"correct":correct,"explanation":q["explanation"]})
        attempt.profile_json=profile_to_json(profile); attempt.history_json=json.dumps(history)
        attempt.question_number+=1; attempt.current_question_json=""
        db.session.commit()
        if attempt.question_number>=assessment.question_count: finish_attempt(attempt)
        return redirect(url_for("report",attempt_id=attempt.id) if attempt.status=="completed" else url_for("take_assessment"))
    try:
        q=get_or_create_question(attempt)
    except Exception as exc:
        app.logger.exception("Question generation failed")
        flash(f"Could not generate the next question: {exc}. Your previous answers are saved; retry below.","error")
        q=None
    remaining=max(0,int((attempt.expires_at-datetime.utcnow()).total_seconds())) if attempt.expires_at else None
    return render_template("take.html",attempt=attempt,assessment=assessment,q=q,remaining=remaining)

@app.route("/retry-question",methods=["POST"])
def retry_question():
    attempt=current_attempt()
    if not attempt: return redirect(url_for("index"))
    attempt.current_question_json=""; db.session.commit()
    return redirect(url_for("take_assessment"))

@app.route("/report/<int:attempt_id>")
def report(attempt_id):
    attempt=db.session.get(Attempt,attempt_id)
    if not attempt: abort(404)
    if attempt.status!="completed" and not (current_user.is_authenticated and attempt.assessment.recruiter_id==current_user.id):
        abort(403)
    history=json.loads(attempt.history_json or "[]")
    profile=profile_from_json(attempt.candidate_name,attempt.profile_json)
    mastery=profile.knowledge
    strongest=max(mastery.items(),key=lambda x:x[1].mastery)[0] if mastery else "—"
    weakest=min(mastery.items(),key=lambda x:x[1].mastery)[0] if mastery else "—"
    return render_template("report.html",attempt=attempt,history=history,mastery=mastery,strongest=strongest,weakest=weakest)

@app.route("/free-test",methods=["GET","POST"])
def free_test():
    if request.method=="POST":
        topic=request.form.get("topic","").strip()
        name=request.form.get("name","").strip() or "Practice learner"
        try:
            count=max(1,min(30,int(request.form.get("question_count",10))))
            duration=max(5,min(240,int(request.form.get("duration",30))))
        except ValueError: count,duration=10,30
        if not topic: flash("Enter any topic to practice.","error")
        else:
            a=Assessment(recruiter_id=None,title="Free practice",topic=topic,question_count=count,duration_minutes=duration,
                token=secrets.token_urlsafe(24),kind="practice")
            db.session.add(a); db.session.flush()
            at=Attempt(assessment=a,candidate_name=name,started_at=datetime.utcnow(),
                expires_at=datetime.utcnow()+timedelta(minutes=duration),status="in_progress")
            db.session.add(at); db.session.commit(); session["attempt_id"]=at.id
            return redirect(url_for("take_assessment"))
    return render_template("free_test.html")

@app.route("/recruiter/attempt/<int:attempt_id>")
@login_required
def recruiter_attempt_report(attempt_id):
    at=db.session.get(Attempt,attempt_id)
    if not at or at.assessment.recruiter_id!=current_user.id: abort(404)
    return redirect(url_for("report",attempt_id=attempt_id))

@app.route("/health")
def health(): return {"status":"ok"}

with app.app_context():
    db.create_all()

if __name__=="__main__":
    app.run(debug=os.getenv("FLASK_DEBUG","0")=="1")
