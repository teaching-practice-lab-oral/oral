from app.utils import taipei_now
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime, Text, Numeric,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, func, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.config import settings
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    student_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    email = Column(String(256), nullable=False)
    backup_email = Column(String(256), nullable=True)
    hashed_password = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False, default="student")  # 'student' | 'admin'
    course_num = Column(String(64), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, server_default="false", nullable=False)
    privacy_notice_version = Column(String(32), nullable=True)
    privacy_acknowledged_at = Column(DateTime, nullable=True)
    system_terms_version = Column(String(32), nullable=True)
    system_terms_accepted_at = Column(DateTime, nullable=True)
    session_version = Column(Integer, nullable=False, default=1, server_default="1")
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, server_default=func.now(), nullable=False)

    submissions = relationship("Submission", back_populates="user", lazy="dynamic")
    api_logs = relationship("ApiUsageLog", back_populates="user", lazy="dynamic")
    costly_action_logs = relationship(
        "CostlyActionUsageLog",
        back_populates="user",
        lazy="dynamic",
        passive_deletes=True,
    )
    created_assignments = relationship("Assignment", back_populates="creator", lazy="dynamic")
    assignment_reminders = relationship(
        "AssignmentReminder",
        foreign_keys="AssignmentReminder.user_id",
        lazy="dynamic",
    )

    password_reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("role IN ('student', 'admin')", name="ck_users_role"),
        CheckConstraint(
            "role = 'student' OR backup_email IS NULL",
            name="ck_users_admin_backup_email_null",
        ),
        CheckConstraint("session_version >= 1", name="ck_users_session_version_positive"),
        CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count_nonnegative"),
        CheckConstraint(
            "(privacy_notice_version IS NULL) = (privacy_acknowledged_at IS NULL)",
            name="ck_users_privacy_ack_pair",
        ),
        CheckConstraint(
            "(system_terms_version IS NULL) = (system_terms_accepted_at IS NULL)",
            name="ck_users_terms_ack_pair",
        ),
        Index("ix_users_is_active_role", "is_active", "role"),
    )

    @property
    def is_protected_admin(self) -> bool:
        return bool(settings.PROTECTED_ADMIN_STUDENT_ID) and self.student_id == settings.PROTECTED_ADMIN_STUDENT_ID

    @property
    def is_privileged_admin(self) -> bool:
        return self.is_protected_admin


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    questions = Column(JSONB, nullable=False)
    question_set_key = Column(String(64), nullable=True)
    course_nums = Column(JSONB(none_as_null=True), nullable=True)  # list of class names; SQL NULL = visible to all
    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    prompt_context = Column(Text, nullable=True)
    rubric_version_id = Column(Integer, ForeignKey("rubric_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, server_default=func.now(), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    creator = relationship("User", back_populates="created_assignments")
    submissions = relationship(
        "Submission",
        back_populates="assignment",
        lazy="dynamic",
        passive_deletes=True,
    )
    reminders = relationship(
        "AssignmentReminder",
        foreign_keys="AssignmentReminder.assignment_id",
        lazy="dynamic",
        passive_deletes=True,
    )
    rubric_version = relationship("RubricVersion", foreign_keys=[rubric_version_id])

    __table_args__ = (
        CheckConstraint(
            "start_date IS NULL OR due_date IS NULL OR due_date >= start_date",
            name="ck_assignments_due_after_start",
        ),
        CheckConstraint(
            "course_nums IS NULL OR jsonb_typeof(course_nums) IN ('array', 'null')",
            name="ck_assignments_course_nums_array",
        ),
        CheckConstraint(
            "questions IS NULL OR jsonb_typeof(questions) IN ('array', 'null')",
            name="ck_assignments_questions_array",
        ),
        CheckConstraint(
            "CASE WHEN jsonb_typeof(questions) = 'array' THEN CASE "
            "WHEN jsonb_array_length(questions) = 4 THEN "
            "jsonb_typeof(questions->0) = 'string' AND btrim(questions->>0) <> '' AND "
            "jsonb_typeof(questions->1) = 'string' AND btrim(questions->>1) <> '' AND "
            "jsonb_typeof(questions->2) = 'string' AND btrim(questions->>2) <> '' AND "
            "jsonb_typeof(questions->3) = 'string' AND btrim(questions->>3) <> '' "
            "ELSE FALSE END ELSE FALSE END",
            name="ck_assignments_questions_four",
        ),
        CheckConstraint(
            "question_set_key IS NULL OR question_set_key IN ("
            "'background_motivation', 'skills_achievements', 'situational_problem_solving', "
            "'work_attitude_soft_skills', 'company_future')",
            name="ck_assignments_question_set_key",
        ),
        Index("ix_assignments_created_by", "created_by"),
        Index("ix_assignments_active_due_date", is_active, due_date),
        Index("ix_assignments_created_at_desc", created_at.desc()),
    )


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    question_set_key = Column(String(64), nullable=True)
    attempt_number = Column(Integer, default=1, nullable=False)
    stage = Column(Integer, default=1, nullable=False)  # current stage 1-9
    workflow_version = Column(Integer, default=2, nullable=False, server_default="2")
    rubric_version_id = Column(Integer, ForeignKey("rubric_versions.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Stage 3 - AI Feedback on Draft 1
    draft2_ai_feedback = Column(JSONB, nullable=True)
    feedback_count = Column(Integer, default=0, nullable=False, server_default="0")

    late_deadline = Column(DateTime, nullable=True)
    practice_started_at = Column(DateTime, nullable=True)
    practice_deadline_at = Column(DateTime, nullable=True)
    practice_completed_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    user = relationship("User", back_populates="submissions")
    assignment = relationship("Assignment", back_populates="submissions")
    question_rows = relationship(
        "SubmissionQuestion",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionQuestion.question_index",
    )
    answer_rows = relationship(
        "SubmissionAnswer",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionAnswer.question_index",
    )
    shadowing_records = relationship(
        "ShadowingRecord",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="ShadowingRecord.question_index",
    )
    roleplay_turn_rows = relationship(
        "RoleplayTurn",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="RoleplayTurn.turn_number",
    )
    proctor_events = relationship(
        "SubmissionProctorEvent",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionProctorEvent.created_at",
    )
    report_row = relationship(
        "SubmissionReport",
        back_populates="submission",
        cascade="all, delete-orphan",
        uselist=False,
    )
    job_profile = relationship(
        "SubmissionJobProfile",
        back_populates="submission",
        cascade="all, delete-orphan",
        uselist=False,
    )
    reflection = relationship(
        "SubmissionReflection",
        back_populates="submission",
        cascade="all, delete-orphan",
        uselist=False,
    )
    rubric_version = relationship("RubricVersion", foreign_keys=[rubric_version_id])

    __table_args__ = (
        UniqueConstraint("user_id", "assignment_id", "attempt_number", name="uq_submission_attempt"),
        CheckConstraint("attempt_number >= 1", name="ck_submissions_attempt_positive"),
        CheckConstraint("stage BETWEEN 1 AND 9", name="ck_submissions_stage_range"),
        CheckConstraint("workflow_version = 2", name="ck_submissions_workflow_version"),
        CheckConstraint("feedback_count >= 0", name="ck_submissions_feedback_count_nonnegative"),
        CheckConstraint(
            "question_set_key IS NULL OR question_set_key IN ("
            "'background_motivation', 'skills_achievements', 'situational_problem_solving', "
            "'work_attitude_soft_skills', 'company_future')",
            name="ck_submissions_question_set_key",
        ),
        CheckConstraint(
            "submitted_at IS NULL OR stage >= 9",
            name="ck_submissions_submitted_stage",
        ),
        Index("ix_submissions_assignment_submitted", "assignment_id", "submitted_at"),
    )


class SubmissionQuestion(Base):
    __tablename__ = "submission_questions"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    question_index = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="question_rows")

    __table_args__ = (
        UniqueConstraint("submission_id", "question_index", name="uq_submission_questions_submission_index"),
        CheckConstraint("question_index >= 0", name="ck_submission_questions_index_nonnegative"),
    )


class SubmissionAnswer(Base):
    __tablename__ = "submission_answers"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    answer_type = Column(String(16), nullable=False)
    question_index = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="answer_rows")

    __table_args__ = (
        UniqueConstraint("submission_id", "answer_type", "question_index", name="uq_submission_answers_type_index"),
        CheckConstraint("answer_type IN ('draft1', 'final')", name="ck_submission_answers_type"),
        CheckConstraint("question_index >= 0", name="ck_submission_answers_index_nonnegative"),
    )


class ShadowingRecord(Base):
    __tablename__ = "shadowing_records"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    question_index = Column(Integer, nullable=False)
    tts_key = Column(String(512), nullable=True)
    tts_timing = Column(JSONB, nullable=True)
    audio_key = Column(String(512), nullable=True)
    transcript = Column(Text, nullable=True)
    metrics = Column(JSONB, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="shadowing_records")

    __table_args__ = (
        UniqueConstraint("submission_id", "question_index", name="uq_shadowing_records_submission_index"),
        CheckConstraint("question_index >= 0", name="ck_shadowing_records_index_nonnegative"),
        CheckConstraint("attempts >= 0", name="ck_shadowing_records_attempts_nonnegative"),
    )


class RoleplayTurn(Base):
    __tablename__ = "roleplay_turns"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    turn_number = Column(Integer, nullable=False)
    source_question_index = Column(Integer, nullable=True)
    interviewer_question = Column(Text, nullable=False)
    interviewer_tts_key = Column(String(512), nullable=True)
    student_transcript = Column(Text, nullable=True)
    student_audio_key = Column(String(512), nullable=True)
    student_metrics = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="roleplay_turn_rows")

    __table_args__ = (
        UniqueConstraint("submission_id", "turn_number", name="uq_roleplay_turns_submission_turn"),
        CheckConstraint("turn_number >= 1", name="ck_roleplay_turns_turn_positive"),
        CheckConstraint(
            "source_question_index IS NULL OR source_question_index BETWEEN 0 AND 4",
            name="ck_roleplay_turns_source_question_index",
        ),
    )


class SubmissionProctorEvent(Base):
    __tablename__ = "submission_proctor_events"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(32), nullable=False)
    page_path = Column(String(160), nullable=False)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="proctor_events")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('fullscreen_enter', 'fullscreen_exit', 'page_hidden', "
            "'window_blur', 'paste_blocked', 'large_input', 'time_expired')",
            name="ck_submission_proctor_events_type",
        ),
        Index("ix_submission_proctor_events_submission_created", "submission_id", "created_at"),
    )


class SubmissionReport(Base):
    __tablename__ = "submission_reports"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    report_data = Column(JSONB, nullable=False)
    input_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="report_row")

    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_submission_reports_submission_id"),
    )


class SubmissionJobProfile(Base):
    __tablename__ = "submission_job_profiles"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    desired_position = Column(String(200), nullable=False)
    role_description = Column(Text, nullable=False)
    required_competencies = Column(Text, nullable=False)
    additional_notes = Column(Text, nullable=True)
    learning_scaffold = Column(JSONB, nullable=True)
    scaffold_input_hash = Column(String(64), nullable=True)
    scaffold_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="job_profile")

    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_submission_job_profiles_submission_id"),
        Index("ix_submission_job_profiles_submission_id", "submission_id"),
    )


class SubmissionReflection(Base):
    __tablename__ = "submission_reflections"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    has_issue = Column(Boolean, nullable=False, default=False, server_default="false")
    issue_category = Column(String(32), nullable=True)
    issue_description = Column(Text, nullable=True)
    photo_key = Column(String(512), nullable=True)
    photo_content_type = Column(String(64), nullable=True)
    photo_original_name = Column(String(256), nullable=True)
    photo_size = Column(Integer, nullable=True)
    photo_validation_version = Column(Integer, nullable=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    submission = relationship("Submission", back_populates="reflection")
    answers = relationship(
        "SubmissionReflectionAnswer",
        back_populates="reflection",
        cascade="all, delete-orphan",
        order_by="SubmissionReflectionAnswer.question_index",
    )

    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_submission_reflections_submission_id"),
        CheckConstraint(
            "submitted_at IS NULL OR NOT has_issue OR "
            "(issue_category IS NOT NULL AND btrim(issue_category) <> '' "
            "AND issue_description IS NOT NULL AND btrim(issue_description) <> '')",
            name="ck_submission_reflections_issue_detail",
        ),
        CheckConstraint("photo_size IS NULL OR photo_size BETWEEN 1 AND 10485760", name="ck_submission_reflections_photo_size"),
        CheckConstraint(
            "photo_validation_version IS NULL OR photo_validation_version = 1",
            name="ck_submission_reflections_photo_validation_version",
        ),
        CheckConstraint("revision >= 1", name="ck_submission_reflections_revision_positive"),
        Index("ix_submission_reflections_submission_id", "submission_id"),
        Index(
            "ix_submission_reflections_issue_submitted",
            "has_issue",
            "submitted_at",
            postgresql_where=has_issue.is_(True),
        ),
    )


class SubmissionReflectionAnswer(Base):
    __tablename__ = "submission_reflection_answers"

    id = Column(Integer, primary_key=True)
    reflection_id = Column(Integer, ForeignKey("submission_reflections.id", ondelete="CASCADE"), nullable=False)
    question_index = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    reflection = relationship("SubmissionReflection", back_populates="answers")

    __table_args__ = (
        UniqueConstraint("reflection_id", "question_index", name="uq_reflection_answers_reflection_index"),
        CheckConstraint("question_index >= 0", name="ck_reflection_answers_index_nonnegative"),
        Index("ix_reflection_answers_reflection_index", "reflection_id", "question_index"),
    )


class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, nullable=False, default=False, server_default="false")
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    versions = relationship("RubricVersion", back_populates="rubric", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_rubrics_archived_name", "is_archived", "name"),
        Index(
            "uq_rubrics_single_system",
            "is_system",
            unique=True,
            postgresql_where=is_system.is_(True),
        ),
    )


class RubricVersion(Base):
    __tablename__ = "rubric_versions"

    id = Column(Integer, primary_key=True)
    rubric_id = Column(Integer, ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="draft", server_default="draft")
    definition = Column(JSONB, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    published_at = Column(DateTime, nullable=True)

    rubric = relationship("Rubric", back_populates="versions")

    __table_args__ = (
        UniqueConstraint("rubric_id", "version_number", name="uq_rubric_versions_rubric_version"),
        CheckConstraint("version_number >= 1", name="ck_rubric_versions_number_positive"),
        CheckConstraint("status IN ('draft', 'published')", name="ck_rubric_versions_status"),
        CheckConstraint("jsonb_typeof(definition) = 'object'", name="ck_rubric_versions_definition_object"),
        Index("ix_rubric_versions_status_created", "status", "created_at"),
    )


class SubmissionGradeRevision(Base):
    """Append-only grading ledger; origin identifiers intentionally survive parent deletion."""

    __tablename__ = "submission_grade_revisions"

    id = Column(Integer, primary_key=True)
    origin_submission_id = Column(Integer, nullable=False)
    origin_assignment_id = Column(Integer, nullable=False)
    origin_user_id = Column(Integer, nullable=False)
    revision_number = Column(Integer, nullable=False)
    rubric_version_id = Column(Integer, nullable=False)
    rubric_name = Column(String(200), nullable=False)
    rubric_version_number = Column(Integer, nullable=False)
    rubric_snapshot = Column(JSONB, nullable=False)
    ratings_json = Column(JSONB, nullable=False)
    rubric_score = Column(Numeric(5, 2), nullable=False)
    final_score = Column(Numeric(4, 1), nullable=False)
    teacher_comment = Column(Text, nullable=False)
    teacher_feedback = Column(Text, nullable=False)
    change_reason = Column(Text, nullable=True)
    grader_user_id = Column(Integer, nullable=False)
    grader_student_id = Column(String(64), nullable=False)
    grader_name = Column(String(128), nullable=True)
    student_id_snapshot = Column(String(64), nullable=False)
    student_name_snapshot = Column(String(128), nullable=False)
    assignment_title_snapshot = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=taipei_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("origin_submission_id", "revision_number", name="uq_grade_revisions_submission_revision"),
        CheckConstraint("revision_number >= 1", name="ck_grade_revisions_revision_positive"),
        CheckConstraint("rubric_score BETWEEN 0 AND 100", name="ck_grade_revisions_rubric_score"),
        CheckConstraint("final_score BETWEEN 0 AND 100", name="ck_grade_revisions_final_score"),
        Index("ix_grade_revisions_submission_latest", "origin_submission_id", created_at.desc(), id.desc()),
        Index("ix_grade_revisions_assignment_created", "origin_assignment_id", created_at.desc()),
    )


class ApiUsageLog(Base):
    __tablename__ = "api_usage_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stage = Column(Integer, nullable=False)
    called_at = Column(DateTime, default=taipei_now, nullable=False)

    user = relationship("User", back_populates="api_logs")

    __table_args__ = (
        CheckConstraint("stage IN (1, 3, 5, 6, 7)", name="ck_api_usage_logs_stage"),
        Index("ix_api_usage_user_called", "user_id", "called_at"),
        Index("ix_api_usage_user_stage_called", "user_id", "stage", "called_at"),
    )


class CostlyActionUsageLog(Base):
    """Short-lived, cluster-wide admission log for attacker-controlled costly work."""

    __tablename__ = "costly_action_usage_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(32), nullable=False)
    resource_id = Column(String(64), nullable=True)
    units_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    called_at = Column(DateTime, default=taipei_now, server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="costly_action_logs")

    __table_args__ = (
        CheckConstraint(
            "action IN ('audio_upload', 'photo_upload', 'student_result_export')",
            name="ck_costly_action_usage_logs_action",
        ),
        CheckConstraint("units_bytes >= 0", name="ck_costly_action_usage_logs_units_nonnegative"),
        Index("ix_costly_action_user_action_called", "user_id", "action", "called_at"),
        Index("ix_costly_action_action_resource_called", "action", "resource_id", "called_at"),
    )


class ActiveSession(Base):
    __tablename__ = "active_sessions"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    device_type = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=taipei_now, server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime, default=taipei_now, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint(
            "device_type IS NULL OR device_type IN ('mobile', 'tablet', 'desktop', 'unknown')",
            name="ck_active_sessions_device_type",
        ),
        CheckConstraint("expires_at >= created_at", name="ck_active_sessions_expires_after_created"),
        Index("ix_active_sessions_expires_at", "expires_at"),
        Index("ix_active_sessions_last_seen_expires", "last_seen_at", "expires_at"),
    )


class StudentPresence(Base):
    __tablename__ = "student_presence"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    active_session_id = Column(Integer, ForeignKey("active_sessions.id", ondelete="SET NULL"), nullable=True, unique=True)
    ip_address = Column(String(64), nullable=True)
    device_type = Column(String(32), nullable=True)
    last_seen_at = Column(DateTime, default=taipei_now, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    active_session = relationship("ActiveSession", foreign_keys=[active_session_id])

    __table_args__ = (
        CheckConstraint(
            "device_type IS NULL OR device_type IN ('mobile', 'tablet', 'desktop', 'unknown')",
            name="ck_student_presence_device_type",
        ),
        CheckConstraint("expires_at >= last_seen_at", name="ck_student_presence_expires_after_seen"),
        Index("ix_student_presence_expires_at", "expires_at"),
        Index("ix_student_presence_last_seen", "last_seen_at"),
    )


class LoginEvent(Base):
    __tablename__ = "login_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    student_id = Column(String(64), nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    device_type = Column(String(32), nullable=True)  # 'mobile' | 'tablet' | 'desktop' | 'unknown'
    success = Column(Boolean, nullable=False)
    login_at = Column(DateTime, default=taipei_now, server_default=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint(
            "device_type IS NULL OR device_type IN ('mobile', 'tablet', 'desktop', 'unknown')",
            name="ck_login_events_device_type",
        ),
        Index("ix_login_events_ip_login_at", "ip_address", "login_at"),
        Index("ix_login_events_login_at", "login_at"),
        Index("ix_login_events_user_login_at", user_id, login_at.desc()),
        Index("ix_login_events_success_login_at", success, login_at.desc()),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    request_ip = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=taipei_now, server_default=func.now(), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="password_reset_tokens")

    __table_args__ = (
        CheckConstraint("expires_at >= created_at", name="ck_password_reset_tokens_expires_after_created"),
        Index("ix_password_reset_tokens_user_created", "user_id", created_at.desc()),
        Index("ix_password_reset_tokens_ip_created", "request_ip", created_at.desc()),
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    admin_student_id = Column(String(64), nullable=False, index=True)
    admin_name = Column(String(128), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), nullable=True, index=True)
    target_id = Column(String(64), nullable=True, index=True)
    target_label = Column(String(256), nullable=True)
    result = Column(String(16), nullable=False, default="success", server_default="success")
    summary = Column(Text, nullable=True)
    before_json = Column(JSONB, nullable=True)
    after_json = Column(JSONB, nullable=True)
    detail_json = Column(JSONB, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False, index=True)

    admin = relationship("User", foreign_keys=[admin_user_id])

    __table_args__ = (
        CheckConstraint("result IN ('success', 'failure')", name="ck_admin_audit_logs_result"),
        Index("ix_admin_audit_logs_created_id_desc", created_at.desc(), id.desc()),
        Index("ix_admin_audit_logs_action_created", action, created_at.desc()),
        Index("ix_admin_audit_logs_target_type_created", target_type, created_at.desc()),
    )


class EmailJob(Base):
    """Shared database-backed progress for account and result deliveries."""

    __tablename__ = "email_jobs"

    id = Column(String(36), primary_key=True)
    kind = Column(String(32), nullable=False)
    assignment_id = Column(
        Integer,
        ForeignKey("assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    state = Column(String(16), nullable=False, default="queued", server_default="queued")
    total = Column(Integer, nullable=False, default=0)
    processed = Column(Integer, nullable=False, default=0)
    succeeded = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    details = Column(JSONB, nullable=False, default=dict, server_default="{}")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('account', 'result_package')",
            name="ck_email_jobs_kind",
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed')",
            name="ck_email_jobs_state",
        ),
        CheckConstraint("total >= 0", name="ck_email_jobs_total_nonnegative"),
        CheckConstraint("processed >= 0", name="ck_email_jobs_processed_nonnegative"),
        CheckConstraint("succeeded >= 0", name="ck_email_jobs_succeeded_nonnegative"),
        CheckConstraint("failed >= 0", name="ck_email_jobs_failed_nonnegative"),
        CheckConstraint("processed <= total", name="ck_email_jobs_processed_within_total"),
        CheckConstraint(
            "succeeded + failed <= processed",
            name="ck_email_jobs_results_within_processed",
        ),
        CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name="ck_email_jobs_details_object",
        ),
        Index("ix_email_jobs_assignment_created", "assignment_id", created_at.desc()),
        Index(
            "uq_email_jobs_active_result_assignment",
            "assignment_id",
            unique=True,
            postgresql_where=text(
                "kind = 'result_package' AND state IN ('queued', 'running')"
            ),
        ),
    )


class ResultPackage(Base):
    """A private, expiring result ZIP plus per-mailbox delivery state."""

    __tablename__ = "result_packages"

    id = Column(String(36), primary_key=True)
    job_id = Column(
        String(36),
        ForeignKey("email_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_id = Column(
        Integer,
        ForeignKey("assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submission_id = Column(
        Integer,
        ForeignKey("submissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    grade_revision_id = Column(
        Integer,
        ForeignKey("submission_grade_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id_snapshot = Column(String(64), nullable=False)
    student_name_snapshot = Column(String(128), nullable=False)
    assignment_title_snapshot = Column(String(256), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    filename = Column(String(256), nullable=False)
    object_key = Column(String(512), nullable=True, unique=True)
    token_hash = Column(String(64), nullable=True, unique=True, index=True)
    state = Column(String(16), nullable=False, default="queued", server_default="queued")
    recipients = Column(JSONB, nullable=False, default=list, server_default="[]")
    error = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)
    updated_at = Column(DateTime, default=taipei_now, onupdate=taipei_now, nullable=False)

    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="ck_result_packages_attempt_positive"),
        CheckConstraint(
            "state IN ('queued', 'building', 'sending', 'sent', 'partial', 'failed', 'expired')",
            name="ck_result_packages_state",
        ),
        CheckConstraint(
            "jsonb_typeof(recipients) = 'array'",
            name="ck_result_packages_recipients_array",
        ),
        CheckConstraint(
            "(object_key IS NULL) = (token_hash IS NULL)",
            name="ck_result_packages_object_token_pair",
        ),
        CheckConstraint(
            "object_key IS NULL OR expires_at IS NOT NULL",
            name="ck_result_packages_object_expiry",
        ),
        Index("ix_result_packages_job_state", "job_id", "state"),
        Index("ix_result_packages_expires_state", "expires_at", "state"),
    )


class AssignmentReminder(Base):
    """One row per (assignment, student) reminder already sent — the UNIQUE constraint
    makes the 72h-before-due reminder idempotent no matter how often the job runs."""
    __tablename__ = "assignment_reminders"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_at = Column(DateTime, default=taipei_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("assignment_id", "user_id", name="uq_assignment_reminder"),
    )


class ObjectDeletionTask(Base):
    """Transactional outbox for idempotent object-storage deletion."""

    __tablename__ = "object_deletion_tasks"

    id = Column(Integer, primary_key=True)
    target_type = Column(String(16), nullable=False, default="prefix", server_default="prefix")
    target = Column(String(512), nullable=False)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime, default=taipei_now, nullable=False, index=True)
    last_error = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=taipei_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("target_type", "target", name="uq_object_deletion_tasks_target"),
        CheckConstraint(
            "target_type IN ('key', 'prefix')",
            name="ck_object_deletion_tasks_target_type",
        ),
        CheckConstraint("attempts >= 0", name="ck_object_deletion_tasks_attempts_nonnegative"),
        Index(
            "ix_object_deletion_tasks_pending",
            next_attempt_at,
            postgresql_where=completed_at.is_(None),
        ),
    )
