from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager

class User(UserMixin, db.Model):
    id=db.Column(db.Integer,primary_key=True)
    company=db.Column(db.String(160),nullable=False)
    name=db.Column(db.String(120),nullable=False)
    email=db.Column(db.String(180),unique=True,nullable=False,index=True)
    password_hash=db.Column(db.String(255),nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    def set_password(self,p): self.password_hash=generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)

class Assessment(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    recruiter_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=True,index=True)
    title=db.Column(db.String(180),nullable=False)
    topic=db.Column(db.String(300),nullable=False)
    question_count=db.Column(db.Integer,default=10)
    duration_minutes=db.Column(db.Integer,default=30)
    token=db.Column(db.String(64),unique=True,index=True,nullable=False)
    kind=db.Column(db.String(20),default="recruiter")
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    recruiter=db.relationship("User",backref="assessments")
    attempts=db.relationship("Attempt",backref="assessment",cascade="all, delete-orphan")

class Attempt(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    assessment_id=db.Column(db.Integer,db.ForeignKey("assessment.id"),nullable=False,index=True)
    candidate_name=db.Column(db.String(140),nullable=False)
    candidate_email=db.Column(db.String(180),default="")
    profile_json=db.Column(db.Text,default="{}")
    history_json=db.Column(db.Text,default="[]")
    current_question_json=db.Column(db.Text,default="")
    question_number=db.Column(db.Integer,default=0)
    started_at=db.Column(db.DateTime)
    expires_at=db.Column(db.DateTime)
    completed_at=db.Column(db.DateTime)
    status=db.Column(db.String(20),default="not_started")
    score=db.Column(db.Float,default=0)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
