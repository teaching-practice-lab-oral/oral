import re
from datetime import datetime
from typing import Optional, List, Any, Dict, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

_PROMPT_INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instruction",
    re.IGNORECASE,
)
_PROMPT_CONTEXT_MAX_LEN = 3000
_PROMPT_TEMPLATE_MAX_LEN = 60000


def _validate_prompt_context(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = v.strip()
    if len(v) > _PROMPT_CONTEXT_MAX_LEN:
        raise ValueError(f"prompt_context 不可超過 {_PROMPT_CONTEXT_MAX_LEN} 個字元")
    if _PROMPT_INJECTION_RE.search(v):
        raise ValueError("prompt_context 包含不允許的指令覆寫語句")
    return v


PASSWORD_MIN_LEN = 8


def validate_password(v: str) -> str:
    """Shared password policy used by all password-setting endpoints."""
    if v is None or len(v) < PASSWORD_MIN_LEN:
        raise ValueError(f"密碼至少需要 {PASSWORD_MIN_LEN} 個字元")
    return v


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    student_id: str
    password: str
    turnstile_token: str = ""

    @field_validator("student_id")
    @classmethod
    def _normalize_student_id(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("學號不可空白")
        return value


class LoginResponse(BaseModel):
    role: str
    name: str
    user_id: int
    must_change_password: bool = False
    requires_legal_acknowledgement: bool = False
    is_privileged_admin: bool = False


class PasswordResetRequestCreate(BaseModel):
    course_num: str
    name: str
    student_id: str
    backup_email: Optional[EmailStr] = None
    turnstile_token: str = ""

    @field_validator("course_num", "name", "student_id")
    @classmethod
    def _required_text(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("欄位不可空白")
        return value


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str
    confirm_password: str

    @field_validator("token")
    @classmethod
    def _required_token(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("重設連結無效")
        return value

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password(v)

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("兩次輸入的密碼不一致")
        return self


class UserMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: str
    name: str
    email: str
    role: str
    is_active: bool
    must_change_password: bool = False
    requires_legal_acknowledgement: bool = False
    is_privileged_admin: bool = False
    is_protected_admin: bool = False

# ── User ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    student_id: str
    name: str
    email: EmailStr
    backup_email: Optional[EmailStr] = None
    password: str
    role: str = "student"
    course_num: Optional[str] = None

    @field_validator("student_id", "name")
    @classmethod
    def _required_text(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("欄位不可空白")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password(v)

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in {"student", "admin"}:
            raise ValueError("role 必須是 student 或 admin")
        return v

    @field_validator("course_num")
    @classmethod
    def _normalize_course_num(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        return value or None


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    backup_email: Optional[EmailStr] = None
    course_num: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"student", "admin"}:
            raise ValueError("role 必須是 student 或 admin")
        return v

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("姓名不可空白")
        return value

    @field_validator("course_num")
    @classmethod
    def _normalize_course_num(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        return value or None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: str
    name: str
    email: str
    backup_email: Optional[str] = None
    role: str
    course_num: Optional[str] = None
    is_active: bool
    must_change_password: bool = False
    is_protected_admin: bool = False
    created_at: datetime

class UserListResponse(BaseModel):
    total: int
    users: List[UserResponse]


class UserMailActionResponse(BaseModel):
    message: str
    email_sent: bool = True


class ImportedUserDetail(BaseModel):
    user_id: int
    student_id: str
    name: str
    email: EmailStr
    backup_email: Optional[EmailStr] = None
    password: str
    credential_proof: str
    course_num: Optional[str] = None

    @field_validator("student_id", "name", "password", "credential_proof")
    @classmethod
    def _required_text(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("欄位不可空白")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password(v)

    @field_validator("course_num")
    @classmethod
    def _normalize_course_num(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        return value or None


class ImportSummary(BaseModel):
    total: int
    created: int
    skipped: int
    errors: List[str]
    imported_users: List[ImportedUserDetail] = []


class SendImportEmailsRequest(BaseModel):
    users: List[ImportedUserDetail] = Field(min_length=1, max_length=500)


class EmailJobStartResponse(BaseModel):
    job_id: str
    total: int


class EmailJobStatusResponse(BaseModel):
    job_id: str
    total: int
    sent: int
    failed: int
    done: bool
    failed_emails: List[str] = []


# ── Assignment ────────────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    prompt_context: Optional[str] = None

    @field_validator("prompt_context")
    @classmethod
    def validate_prompt_context(cls, v: Optional[str]) -> Optional[str]:
        return _validate_prompt_context(v)
    question_set_key: Optional[str] = None
    questions: Optional[List[str]] = None
    stage3_template_id: Optional[int] = None
    stage6_template_id: Optional[int] = None
    stage8_template_id: Optional[int] = None
    rubric_version_id: Optional[int] = None
    course_nums: Optional[List[str]] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    is_active: bool = True


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    prompt_context: Optional[str] = None

    @field_validator("prompt_context")
    @classmethod
    def validate_prompt_context(cls, v: Optional[str]) -> Optional[str]:
        return _validate_prompt_context(v)
    question_set_key: Optional[str] = None
    questions: Optional[List[str]] = None
    stage3_template_id: Optional[int] = None
    stage6_template_id: Optional[int] = None
    stage8_template_id: Optional[int] = None
    rubric_version_id: Optional[int] = None
    course_nums: Optional[List[str]] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    is_active: Optional[bool] = None


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str]
    prompt_context: Optional[str]
    questions: Optional[Any]
    question_set_key: Optional[str] = None
    question_scaffolds: Optional[Any] = None
    stage3_template_id: Optional[int] = None
    stage6_template_id: Optional[int] = None
    stage8_template_id: Optional[int] = None
    rubric_version_id: int
    course_nums: Optional[Any] = None
    start_date: Optional[datetime]
    due_date: Optional[datetime]
    is_active: bool
    created_at: datetime
    created_by: Optional[int]

# ── Global Named Prompt Templates ─────────────────────────────────────────────

class GlobalPromptTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stage: Literal[3, 6, 8]
    system_prompt: str = Field(min_length=1, max_length=_PROMPT_TEMPLATE_MAX_LEN)
    roleplay_policy: Optional[str] = Field(default=None, max_length=_PROMPT_TEMPLATE_MAX_LEN)
    secret_question_policy: Optional[str] = Field(default=None, max_length=_PROMPT_TEMPLATE_MAX_LEN)

    @field_validator("name", "system_prompt")
    @classmethod
    def _required_prompt_text(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("欄位不可空白")
        return value

    @field_validator("roleplay_policy", "secret_question_policy")
    @classmethod
    def _optional_prompt_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("Stage 6 規則不可空白")
        return value


class GlobalPromptTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    system_prompt: Optional[str] = Field(default=None, max_length=_PROMPT_TEMPLATE_MAX_LEN)
    roleplay_policy: Optional[str] = Field(default=None, max_length=_PROMPT_TEMPLATE_MAX_LEN)
    secret_question_policy: Optional[str] = Field(default=None, max_length=_PROMPT_TEMPLATE_MAX_LEN)

    @field_validator("name", "system_prompt", "roleplay_policy", "secret_question_policy")
    @classmethod
    def _updated_prompt_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("欄位不可空白")
        return value


class GlobalPromptTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: Optional[str]
    stage: int
    stage_label: str
    system_prompt: str
    is_system: bool
    updated_at: datetime
    roleplay_policy: Optional[str] = None
    secret_question_policy: Optional[str] = None

# ── Submission ────────────────────────────────────────────────────────────────

class QuestionAnswerItem(BaseModel):
    index: int = Field(ge=0)
    question: str
    text: str = Field(min_length=1)


class Draft1AnswersRequest(BaseModel):
    draft1_answers: List[QuestionAnswerItem]


class FinalDraftAnswersRequest(BaseModel):
    final_draft_answers: List[QuestionAnswerItem]


class JobProfilePayload(BaseModel):
    desired_position: str = Field(min_length=1, max_length=200)
    role_description: str = Field(min_length=1, max_length=3000)
    required_competencies: str = Field(min_length=1, max_length=3000)
    additional_notes: Optional[str] = Field(default=None, max_length=3000)

    @field_validator("desired_position", "role_description", "required_competencies")
    @classmethod
    def _strip_required_profile(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("此欄位不可空白")
        return value

    @field_validator("additional_notes")
    @classmethod
    def _strip_optional_profile(cls, v: Optional[str]) -> Optional[str]:
        value = (v or "").strip()
        return value or None


class JobProfileResponse(JobProfilePayload):
    updated_at: Optional[datetime] = None
    is_locked: bool = False


class LearningScaffoldQuestion(BaseModel):
    index: int = Field(ge=0, le=3)
    question: str
    goal: str
    steps: List[str] = Field(min_length=3, max_length=4)
    evidence: str
    role_connection: str
    experience_prompts: List[str] = Field(min_length=2, max_length=2)
    keywords: List[str] = Field(min_length=3, max_length=5)
    sentence_starters: List[str] = Field(min_length=1, max_length=3)
    shadowing_focus: str
    roleplay_focus: str


class LearningScaffoldData(BaseModel):
    schema_version: Literal[1]
    question_set_key: str
    position_focus: str
    competency_priorities: List[str] = Field(min_length=2, max_length=3)
    job_profile_focus: str
    report_focus: str
    reflection_focus: str
    questions: List[LearningScaffoldQuestion] = Field(min_length=4, max_length=4)
    generated_at: datetime


class LearningScaffoldGenerateResponse(BaseModel):
    status: Literal["ready"] = "ready"
    scaffold: LearningScaffoldData


class ReflectionPayload(BaseModel):
    expected_revision: int = Field(ge=0)
    answers: List[str] = Field(min_length=5, max_length=5)
    has_issue: bool = False
    issue_category: Optional[str] = Field(default=None, max_length=32)
    issue_description: Optional[str] = Field(default=None, max_length=3000)

    @field_validator("answers")
    @classmethod
    def _validate_reflection_answers(cls, values: List[str]) -> List[str]:
        return [str(value or "").strip()[:3000] for value in values]


class ReflectionResponse(BaseModel):
    revision: int
    answers: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    has_issue: bool = False
    issue_category: Optional[str] = None
    issue_description: Optional[str] = None
    has_photo: bool = False
    photo_original_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReflectionSubmitRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    assignment_id: int
    question_set_key: Optional[str] = None
    attempt_number: int
    stage: int
    workflow_version: int = 2
    rubric_version_id: int
    draft1_answers: Optional[Any] = None
    draft2_ai_feedback: Optional[Any]
    feedback_count: int = 0
    final_draft_answers: Optional[Any] = None
    shadowing_tts_keys: Optional[Any] = None
    speaking1_attempts: int = 0
    speaking1_questions: Optional[Any] = None
    roleplay_conversation: Optional[str] = None
    report_data: Optional[str] = None
    late_deadline: Optional[datetime] = None
    practice_started_at: Optional[datetime] = None
    practice_deadline_at: Optional[datetime] = None
    practice_completed_at: Optional[datetime] = None
    submitted_at: Optional[datetime]
    updated_at: Optional[datetime]
    questions_snapshot: Optional[Any] = None
    job_profile_data: Optional[Any] = None
    learning_scaffold_status: Literal["not_applicable", "missing", "stale", "ready"] = "not_applicable"
    learning_scaffold: Optional[LearningScaffoldData] = None
    reflection_data: Optional[Any] = None

class WorkflowLimitsResponse(BaseModel):
    max_attempts: int = Field(ge=1)
    max_feedback_count: int = Field(ge=1)
    max_shadowing_attempts: int = Field(ge=1)
    core_question_count: int = Field(ge=1)
    reflection_question_count: int = Field(ge=1)
    secret_question_source_index: int = Field(ge=0)
    max_roleplay_turns: int = Field(ge=1)


class AssignmentWithSubmission(BaseModel):
    assignment: AssignmentResponse
    submission: Optional[SubmissionResponse]
    workflow_limits: WorkflowLimitsResponse


# ── Student assignment list item ──────────────────────────────────────────────

class StudentAssignmentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str]
    start_date: Optional[datetime]
    due_date: Optional[datetime]
    late_deadline: Optional[datetime] = None
    current_stage: int
    attempt_number: int
    is_submitted: bool
    workflow_version: int = 2
    has_job_profile: bool = False
    has_submission_history: bool = False
    has_grade_history: bool = False
    rubric_version_id: int

# ── Admin results ─────────────────────────────────────────────────────────────

class StudentResultItem(BaseModel):
    user_id: int
    student_id: str
    name: str
    email: str
    course_num: Optional[str] = None
    latest_stage: int
    attempt_count: int
    is_submitted: bool
    has_feedback: bool
    grading_status: str = "not_ready"
    latest_final_score: Optional[float] = None
    latest_grader_name: Optional[str] = None
    latest_graded_at: Optional[datetime] = None
    has_issue: bool = False
    late_deadline: Optional[datetime] = None
    updated_at: Optional[datetime]


class AdminDashboardStats(BaseModel):
    total_students: int
    total_assignments: int
    total_submissions: int
    completed_submissions: int
    today_api_calls: int


# ── API Usage Log ─────────────────────────────────────────────────────────────

class ApiUsageLogResponse(BaseModel):
    id: int
    user_id: int
    student_id: Optional[str]
    name: Optional[str]
    stage: int
    called_at: datetime


class ApiUsageLogListResponse(BaseModel):
    total: int
    logs: List[ApiUsageLogResponse]


class WorkerRoutingStatusItem(BaseModel):
    user_id: int
    student_id: str
    name: Optional[str] = None
    role: str
    online: bool
    last_seen_at: Optional[datetime] = None
    submission_id: Optional[int] = None
    assignment_id: Optional[int] = None
    assignment_title: Optional[str] = None
    stage: Optional[int] = None
    stage_label: Optional[str] = None
    operation: Optional[str] = None
    route_status: Optional[str] = None
    route_status_label: Optional[str] = None
    worker_url: Optional[str] = None
    detail: Optional[str] = None
    duration_ms: Optional[int] = None
    routed_at: Optional[datetime] = None


class WorkerRoutingStatusResponse(BaseModel):
    enabled: bool
    base_url: str
    weight: float
    cooldown_seconds: int
    items: List[WorkerRoutingStatusItem]


class WorkerHealthResponse(BaseModel):
    online: bool
    configured: bool
    base_url: str
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    detail: Optional[str] = None
    checked_at: datetime


class ShadowingQuestionRecordingResponse(BaseModel):
    index: int
    transcript: str
    audio_key: str
    attempts: int
    all_done: bool = False


class ShadowingTTSCue(BaseModel):
    text: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def _validate_timing(self):
        if self.end <= self.start:
            raise ValueError("Cue end must be after start")
        return self


class ShadowingTTSAudioResponse(BaseModel):
    url: str
    sync_available: bool = False
    cues: List[ShadowingTTSCue] = Field(default_factory=list)


class RoleplayStartResponse(BaseModel):
    first_question: str
    first_question_source_index: int = 0
    first_question_tts_key: Optional[str] = None
    submission: "SubmissionResponse"


class RoleplayTurnResponse(BaseModel):
    turn_number: int
    source_question_index: int
    student_transcript: str
    student_audio_key: Optional[str] = None
    next_question: Optional[str] = None
    next_question_source_index: Optional[int] = None
    next_question_tts_key: Optional[str] = None
    is_complete: bool
    report: Optional[Any] = None
    pronunciation: Optional[Dict] = None


class ProctorEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=32)
    page_path: str = Field(min_length=1, max_length=160)
    details: Optional[Dict[str, Any]] = None


# ── Submission History ────────────────────────────────────────────────────────

class SubmissionHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    attempt_number: int
    stage: int
    workflow_version: int = 2
    submitted_at: Optional[datetime]
    updated_at: Optional[datetime]
    report_data: Optional[str] = None

# ── Rubrics and grading ──────────────────────────────────────────────────────

class RubricCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    definition: Any

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("評分規準名稱不可空白")
        return value


class RubricVersionUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    definition: Any

    @field_validator("name")
    @classmethod
    def _strip_optional_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("評分規準名稱不可空白")
        return value


class RubricVersionResponse(BaseModel):
    rubric_id: int
    rubric_name: str
    description: Optional[str] = None
    is_system: bool
    is_archived: bool
    version_id: int
    version_number: int
    status: str
    definition: Any
    created_at: datetime
    published_at: Optional[datetime] = None


class GradeCreateRequest(BaseModel):
    ratings: Dict[str, int]
    final_score: float = Field(ge=0, le=100)
    teacher_comment: str = Field(min_length=1, max_length=10000)
    teacher_feedback: str = Field(min_length=1, max_length=10000)
    change_reason: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("teacher_comment", "teacher_feedback")
    @classmethod
    def _strip_grade_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("評語與回饋不可空白")
        return value


class GradeRevisionAdminResponse(BaseModel):
    id: int
    revision_number: int
    rubric_version_id: int
    rubric_name: str
    rubric_version_number: int
    rubric_snapshot: Any
    ratings: Any
    rubric_score: float
    final_score: float
    teacher_comment: str
    teacher_feedback: str
    change_reason: Optional[str]
    grader_student_id: str
    grader_name: Optional[str]
    created_at: datetime


class GradeRevisionStudentResponse(BaseModel):
    revision_number: int
    rubric_name: str
    rubric_version_number: int
    ratings: Any
    final_score: float
    teacher_comment: str
    teacher_feedback: str
    graded_at: datetime


class StudentGradeHistoryItem(GradeRevisionStudentResponse):
    submission_id: int
    attempt_number: int
    change_reason: Optional[str] = None
    grader_student_id: str
    grader_name: Optional[str] = None


# ── Password Reset ────────────────────────────────────────────────────────────

class ResetPasswordRequest(BaseModel):
    new_password: str
    admin_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return validate_password(v)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    privacy_acknowledged: bool = False
    terms_accepted: bool = False

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return validate_password(v)


class LegalAcknowledgementRequest(BaseModel):
    privacy_acknowledged: bool = False
    terms_accepted: bool = False


class MessageResponse(BaseModel):
    message: str


class DeleteConfirmRequest(BaseModel):
    admin_password: str


class LateDeadlineRequest(BaseModel):
    admin_password: str
    late_deadline: Optional[datetime] = None


class BatchLateDeadlineRequest(BaseModel):
    admin_password: str
    user_ids: List[int] = Field(min_length=1)
    late_deadline: Optional[datetime] = None

    @field_validator("user_ids")
    @classmethod
    def _normalize_user_ids(cls, values: List[int]) -> List[int]:
        deduped = []
        seen = set()
        for value in values:
            user_id = int(value)
            if user_id <= 0:
                raise ValueError("user_ids 必須為正整數")
            if user_id in seen:
                continue
            seen.add(user_id)
            deduped.append(user_id)
        if not deduped:
            raise ValueError("至少要選擇一位學生")
        return deduped


# ── Active Sessions ──────────────────────────────────────────────────────────

class ActiveSessionResponse(BaseModel):
    id: int
    user_id: int
    student_id: str
    name: str
    role: str
    ip_address: Optional[str] = None
    device_type: Optional[str] = None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


# ── Login Audit ───────────────────────────────────────────────────────────────

class LoginEventResponse(BaseModel):
    id: int
    student_id: str
    name: Optional[str] = None
    ip_address: Optional[str] = None
    device_type: Optional[str] = None
    success: bool
    login_at: datetime


class LoginEventListResponse(BaseModel):
    items: List[LoginEventResponse]
    total: int
    page: int
    limit: int


class AdminAuditLogResponse(BaseModel):
    id: int
    admin_user_id: Optional[int] = None
    admin_student_id: str
    admin_name: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    target_label: Optional[str] = None
    result: str
    summary: Optional[str] = None
    before_json: Optional[Dict[str, Any] | List[Any]] = None
    after_json: Optional[Dict[str, Any] | List[Any]] = None
    detail_json: Optional[Dict[str, Any] | List[Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: List[AdminAuditLogResponse]
    total: int
    page: int
    limit: int
