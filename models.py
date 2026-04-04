"""
SQLAlchemy models for users, lecture sessions, and attendance rows.

Attendance enforces one mark per user per session via a unique constraint.
"""
import uuid
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    """Application user — either student or admin."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")  # "student" | "admin"

    sessions_created = db.relationship(
        "LectureSession", backref="creator", lazy="dynamic", foreign_keys="LectureSession.admin_id"
    )
    attendance_records = db.relationship("Attendance", backref="user", lazy="dynamic")


class LectureSession(db.Model):
    """A lecture / class session created by an admin (identified in QR by session_id)."""

    __tablename__ = "lecture_sessions"

    # Public id embedded in QR (string UUID — easy to put in a URL or payload)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(200), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    attendance_rows = db.relationship("Attendance", backref="lecture_session", lazy="dynamic")


class Attendance(db.Model):
    """One attendance mark: which student attended which session, when."""

    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_id = db.Column(db.String(36), db.ForeignKey("lecture_sessions.id"), nullable=False)
    # Store date and time separately as requested (also easy to query/report)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "session_id", name="uq_attendance_user_session"),
    )
