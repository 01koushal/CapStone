from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager

class User(UserMixin, db.Model):
    id=db.Column(db.Integer,primary_key=True)
    company=db.Column(db.String(160),nullable=False)
    name=db.Column(db.String(120),nullable=False)
    email=db.Column(db.String(180),unique=True,nullable=False,index=True)
    password_hash=db.Column(db.String(255),nullable=False)
    created_at=db.Column(db.DateTime,default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
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
    description=db.Column(db.Text,default="")
    category=db.Column(db.String(80),default="General")
    instructions=db.Column(db.Text,default="")
    created_at=db.Column(db.DateTime,default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    recruiter=db.relationship("User",backref="assessments")
    attempts=db.relationship("Attempt",backref="assessment",cascade="all, delete-orphan")
    sections=db.relationship("AssessmentSection",backref="assessment",cascade="all, delete-orphan",order_by="AssessmentSection.display_order")

class AssessmentSection(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    assessment_id=db.Column(db.Integer,db.ForeignKey("assessment.id"),nullable=False,index=True)
    name=db.Column(db.String(140),nullable=False)
    description=db.Column(db.Text,default="")
    display_order=db.Column(db.Integer,nullable=False,default=0)
    question_count=db.Column(db.Integer,nullable=False,default=5)
    duration_minutes=db.Column(db.Integer,nullable=False,default=10)
    difficulty_mode=db.Column(db.String(20),nullable=False,default="adaptive")
    topics_json=db.Column(db.Text,nullable=False,default="[]")
    question_types_json=db.Column(db.Text,nullable=False,default='["mcq"]')
    @property
    def topics(self):
        import json
        try: return json.loads(self.topics_json or "[]")
        except (TypeError,ValueError): return []
    @property
    def question_types(self):
        import json
        try: return json.loads(self.question_types_json or '["mcq"]')
        except (TypeError,ValueError): return ["mcq"]

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
    created_at=db.Column(db.DateTime,default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

