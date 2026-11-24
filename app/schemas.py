import re
from datetime import datetime
from typing import Annotated, Optional, List, Any, Dict, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.services.input_validator import normalize_user_text

_PROMPT_INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instruction",
    re.IGNORECASE,
)
_PROMPT_CONTEXT_MAX_LEN = 3000


def _validate_prompt_context(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = normalize_user_text(v, field_name="prompt_context")
    if len(v) > _PROMPT_CONTEXT_MAX_LEN:
        raise ValueError(f"prompt_context 不可超過 {_PROMPT_CONTEXT_MAX_LEN} 個字元")
    if _PROMPT_INJECTION_RE.search(v):
        raise ValueError("prompt_context 包含不允許的指令覆寫語句")
    return v


PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128
PASSWORD_MAX_BYTES = 72

StudentIdText = Annotated[str, Field(min_length=1, max_length=64)]
NameText = Annotated[str, Field(min_length=1, max_length=128)]
CourseText = Annotated[str, Field(min_length=1, max_length=64)]
QuestionText = Annotated[str, Field(min_length=1, max_length=500)]
DraftText = Annotated[str, Field(min_length=1, max_length=2000)]


class StrictRequestModel(BaseModel):
    """Base for request payloads; silently ignored fields are unsafe at boundaries."""

    model_config = ConfigDict(extra="forbid")


def validate_password(v: str) -> str:
    """Shared password policy used by all password-setting endpoints."""
    if v is None or len(v) < PASSWORD_MIN_LEN:
        raise ValueError(f"密碼至少需要 {PASSWORD_MIN_LEN} 個字元")
    if len(v) > PASSWORD_MAX_LEN:
        raise ValueError(f"密碼不可超過 {PASSWORD_MAX_LEN} 個字元")
    if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"密碼的 UTF-8 長度不可超過 {PASSWORD_MAX_BYTES} bytes")
    return v


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(StrictRequestModel):
    student_id: StudentIdText
    password: str = Field(min_length=1, max_length=256)
    turnstile_token: str = Field(default="", max_length=2048)

    @field_validator("student_id")
    @classmethod
    def _normalize_student_id(cls, v: str) -> str:
        value = normalize_user_text(v or "", field_name="學號")
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


class LegalDocumentResponse(BaseModel):
    title: str
    version: str
    url: str


class LegalDocumentsResponse(BaseModel):
    privacy_notice: LegalDocumentResponse
    system_terms: LegalDocumentResponse


class PasswordResetRequestCreate(StrictRequestModel):
    course_num: CourseText
    name: NameText
    student_id: StudentIdText
    backup_email: Optional[EmailStr] = Field(default=None, max_length=256)
    turnstile_token: str = Field(default="", max_length=2048)

    @field_validator("course_num", "name", "student_id")
    @classmethod
    def _required_text(cls, v: str) -> str:
        value = normalize_user_text(v or "", field_name="欄位")
        if not value:
            raise ValueError("欄位不可空白")
        return value


class PasswordResetConfirm(StrictRequestModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)
    confirm_password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)

    @field_validator("token")
    @classmethod
    def _required_token(cls, v: str) -> str:
        value = normalize_user_text(v or "", field_name="token")
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

class UserCreate(StrictRequestModel):
    student_id: StudentIdText
    name: NameText
    email: EmailStr = Field(max_length=256)
    backup_email: Optional[EmailStr] = Field(default=None, max_length=256)
    password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)
    role: Literal["student", "admin"] = "student"
    course_num: Optional[str] = Field(default=None, max_length=64)

    @field_validator("student_id", "name")
    @classmethod
    def _required_text(cls, v: str) -> str:
        value = normalize_user_text(v or "", field_name="欄位")
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
        value = normalize_user_text(v, field_name="班級")
        return value or None


class UserUpdate(StrictRequestModel):
    role: Optional[Literal["student", "admin"]] = None
    is_active: Optional[bool] = None
    name: Optional[str] = Field(default=None, max_length=128)
    email: Optional[EmailStr] = Field(default=None, max_length=256)
    backup_email: Optional[EmailStr] = Field(default=None, max_length=256)
    course_num: Optional[str] = Field(default=None, max_length=64)

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
        value = normalize_user_text(v, field_name="姓名")
        if not value:
            raise ValueError("姓名不可空白")
        return value

    @field_validator("course_num")
    @classmethod
    def _normalize_course_num(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = normalize_user_text(v, field_name="班級")
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


class ImportedUserDetail(StrictRequestModel):
    user_id: int
    student_id: StudentIdText
    name: NameText
    email: EmailStr = Field(max_length=256)
    backup_email: Optional[EmailStr] = Field(default=None, max_length=256)
    password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)
    credential_proof: str = Field(min_length=1, max_length=512)
    course_num: Optional[str] = Field(default=None, max_length=64)

    @field_validator("student_id", "name", "credential_proof")
    @classmethod
    def _required_text(cls, v: str) -> str:
        value = normalize_user_text(v or "", field_name="欄位")
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
        value = normalize_user_text(v, field_name="班級")
        return value or None


class ImportSummary(BaseModel):
    total: int
    created: int
    skipped: int
    errors: List[str]
    imported_users: List[ImportedUserDetail] = []


class SendImportEmailsRequest(StrictRequestModel):
    users: List[ImportedUserDetail] = Field(min_length=1, max_length=500)


class DeliveryJobStartResponse(BaseModel):
    job_id: str
    total: int
    state: str


class DeliveryJobStatusResponse(BaseModel):
    job_id: str
    kind: str
    state: str
    total: int
    processed: int
    succeeded: int
    failed: int
    details: dict = Field(default_factory=dict)
    error: Optional[str] = None


# ── Assignment ────────────────────────────────────────────────────────────────

class AssignmentCreate(StrictRequestModel):
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=4000)
    prompt_context: Optional[str] = Field(default=None, max_length=_PROMPT_CONTEXT_MAX_LEN)

    @field_validator("prompt_context")
    @classmethod
    def validate_prompt_context(cls, v: Optional[str]) -> Optional[str]:
        return _validate_prompt_context(v)
    question_set_key: Optional[Literal[
        "background_motivation", "skills_achievements", "situational_problem_solving",
        "work_attitude_soft_skills", "company_future",
    ]] = None
    questions: Optional[List[QuestionText]] = Field(default=None, min_length=4, max_length=4)
    rubric_version_id: Optional[int] = None
    course_nums: Optional[List[CourseText]] = Field(default=None, max_length=500)
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    is_active: bool = True

    @field_validator("title", "description")
    @classmethod
    def _normalize_assignment_text(cls, value: Optional[str], info) -> Optional[str]:
        if value is None:
            return None
        normalized = normalize_user_text(value, field_name=info.field_name)
        if info.field_name == "title" and not normalized:
            raise ValueError("作業名稱不可空白")
        return normalized or None

    @field_validator("questions")
    @classmethod
    def _normalize_questions(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = [normalize_user_text(value, field_name="面試題目") for value in values]
        if any(not value for value in normalized):
            raise ValueError("面試題目不可空白")
        return normalized

    @field_validator("course_nums")
    @classmethod
    def _normalize_course_nums(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = [normalize_user_text(value, field_name="班級") for value in values]
        if any(not value for value in normalized):
            raise ValueError("班級不可空白")
        return normalized


class AssignmentUpdate(StrictRequestModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=4000)
    prompt_context: Optional[str] = Field(default=None, max_length=_PROMPT_CONTEXT_MAX_LEN)

    @field_validator("prompt_context")
    @classmethod
    def validate_prompt_context(cls, v: Optional[str]) -> Optional[str]:
        return _validate_prompt_context(v)
    question_set_key: Optional[Literal[
        "background_motivation", "skills_achievements", "situational_problem_solving",
        "work_attitude_soft_skills", "company_future",
    ]] = None
    questions: Optional[List[QuestionText]] = Field(default=None, min_length=4, max_length=4)
    rubric_version_id: Optional[int] = None
    course_nums: Optional[List[CourseText]] = Field(default=None, max_length=500)
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    is_active: Optional[bool] = None

    @field_validator("title", "description")
    @classmethod
    def _normalize_assignment_text(cls, value: Optional[str], info) -> Optional[str]:
        if value is None:
            return None
        normalized = normalize_user_text(value, field_name=info.field_name)
        if info.field_name == "title" and not normalized:
            raise ValueError("作業名稱不可空白")
        return normalized or None

    @field_validator("questions")
    @classmethod
    def _normalize_questions(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = [normalize_user_text(value, field_name="面試題目") for value in values]
        if any(not value for value in normalized):
            raise ValueError("面試題目不可空白")
        return normalized

    @field_validator("course_nums")
    @classmethod
    def _normalize_course_nums(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = [normalize_user_text(value, field_name="班級") for value in values]
        if any(not value for value in normalized):
            raise ValueError("班級不可空白")
        return normalized


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str]
    prompt_context: Optional[str]
    questions: Optional[Any]
    question_set_key: Optional[str] = None
    question_scaffolds: Optional[Any] = None
    rubric_version_id: int
    course_nums: Optional[Any] = None
    start_date: Optional[datetime]
    due_date: Optional[datetime]
    is_active: bool
    created_at: datetime
    created_by: Optional[int]

# ── Submission ────────────────────────────────────────────────────────────────

class QuestionAnswerItem(StrictRequestModel):
    index: int = Field(ge=0, le=3)
    # Kept for old static clients, but bind_answers_to_snapshot never trusts it.
    question: str = Field(default="", max_length=500)
    text: DraftText

    @field_validator("question", "text")
    @classmethod
    def _normalize_answer_text(cls, v: str, info) -> str:
        value = normalize_user_text(v, field_name=info.field_name)
        if info.field_name == "text" and not value:
            raise ValueError("答案不可空白")
        return value


class Draft1AnswersRequest(StrictRequestModel):
    draft1_answers: List[QuestionAnswerItem] = Field(min_length=1, max_length=4)


class FinalDraftAnswersRequest(StrictRequestModel):
    final_draft_answers: List[QuestionAnswerItem] = Field(min_length=1, max_length=4)


class JobProfilePayload(StrictRequestModel):
    desired_position: str = Field(min_length=1, max_length=200)
    role_description: str = Field(min_length=1, max_length=3000)
    required_competencies: str = Field(min_length=1, max_length=3000)
    additional_notes: Optional[str] = Field(default=None, max_length=3000)

    @field_validator("desired_position", "role_description", "required_competencies")
    @classmethod
    def _strip_required_profile(cls, v: str) -> str:
        value = normalize_user_text(v, field_name=cls.__name__)
        if not value:
            raise ValueError("此欄位不可空白")
        return value

    @field_validator("additional_notes")
    @classmethod
    def _strip_optional_profile(cls, v: Optional[str]) -> Optional[str]:
        value = normalize_user_text(v or "", field_name="additional_notes")
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
    shadowing_focus: Optional[str] = None  # legacy; no longer generated
    roleplay_focus: str


class LearningScaffoldData(BaseModel):
    schema_version: Literal[1]
    question_set_key: str
    position_focus: str
    competency_priorities: List[str] = Field(min_length=2, max_length=3)
    # Legacy fields, no longer generated.
    job_profile_focus: Optional[str] = None
    report_focus: Optional[str] = None
    reflection_focus: Optional[str] = None
    questions: List[LearningScaffoldQuestion] = Field(min_length=4, max_length=4)
    generated_at: datetime


class LearningScaffoldGenerateResponse(BaseModel):
    status: Literal["ready"] = "ready"
    scaffold: LearningScaffoldData


class ReflectionPayload(StrictRequestModel):
    expected_revision: int = Field(ge=0)
    answers: List[Annotated[str, Field(max_length=3000)]] = Field(min_length=5, max_length=5)
    has_issue: bool = False
    issue_category: Optional[Literal[
        "系統操作", "錄音或音訊", "AI 回饋內容", "網頁顯示", "其他",
    ]] = None
    issue_description: Optional[str] = Field(default=None, max_length=3000)

    @field_validator("answers")
    @classmethod
    def _validate_reflection_answers(cls, values: List[str]) -> List[str]:
        return [normalize_user_text(value or "", field_name="心得答案") for value in values]

    @field_validator("issue_description")
    @classmethod
    def _normalize_issue_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_user_text(value, field_name="問題說明") or None


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


class ReflectionSubmitRequest(StrictRequestModel):
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
    latest_submitted_submission_id: Optional[int] = None
    result_export_submission_id: Optional[int] = None
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
    submission: SubmissionResponse


class ProctorEventDetails(StrictRequestModel):
    mode: Optional[Literal["desktop_shell", "ios_pwa", "android_pwa"]] = None
    screen_width: Optional[int] = Field(default=None, ge=0, le=100_000)
    screen_height: Optional[int] = Field(default=None, ge=0, le=100_000)
    field_id: Optional[str] = Field(default=None, max_length=128)
    character_count: Optional[int] = Field(default=None, ge=0, le=1_000_000)

    @field_validator("field_id")
    @classmethod
    def _normalize_field_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_user_text(value, field_name="field_id") or None


class ProctorEventCreate(StrictRequestModel):
    event_type: Literal[
        "fullscreen_enter", "fullscreen_exit", "page_hidden", "window_blur",
        "paste_blocked", "large_input", "time_expired",
    ]
    page_path: str = Field(min_length=1, max_length=160)
    details: Optional[ProctorEventDetails] = None

    @field_validator("page_path")
    @classmethod
    def _normalize_page_path(cls, value: str) -> str:
        return normalize_user_text(value, field_name="page_path")


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

RubricKey = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$")]


class RubricSharedLevelInput(StrictRequestModel):
    value: int = Field(ge=0, le=100)
    label: str = Field(min_length=1, max_length=120)
    ratio: float = Field(ge=0, le=1)
    anchor: str = Field(min_length=1, max_length=1000)

    @field_validator("label", "anchor")
    @classmethod
    def _normalize_text(cls, value: str, info) -> str:
        return normalize_user_text(value, field_name=info.field_name)


class RubricCriterionLevelInput(StrictRequestModel):
    value: int = Field(ge=0, le=100)
    label: str = Field(min_length=1, max_length=120)
    points: int = Field(ge=0, le=100)
    anchor: str = Field(min_length=1, max_length=1000)

    @field_validator("label", "anchor")
    @classmethod
    def _normalize_text(cls, value: str, info) -> str:
        return normalize_user_text(value, field_name=info.field_name)


class RubricCriterionInput(StrictRequestModel):
    key: RubricKey
    name: str = Field(min_length=1, max_length=120)
    points: int = Field(ge=1, le=100)
    description: str = Field(min_length=1, max_length=1000)
    levels: Optional[List[RubricCriterionLevelInput]] = Field(default=None, min_length=2, max_length=12)

    @field_validator("name", "description")
    @classmethod
    def _normalize_text(cls, value: str, info) -> str:
        return normalize_user_text(value, field_name=info.field_name)


class RubricDimensionInput(StrictRequestModel):
    key: RubricKey
    name: str = Field(min_length=1, max_length=80)
    weight: int = Field(ge=1, le=100)
    criteria: List[RubricCriterionInput] = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return normalize_user_text(value, field_name="評分面向名稱")


class RubricDefinitionInput(StrictRequestModel):
    levels: List[RubricSharedLevelInput] = Field(default_factory=list, max_length=12)
    notes: List[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=10)
    dimensions: List[RubricDimensionInput] = Field(min_length=1, max_length=20)

    @field_validator("notes")
    @classmethod
    def _normalize_notes(cls, values: List[str]) -> List[str]:
        return [normalize_user_text(value, field_name="評分注意事項") for value in values]

class RubricCreateRequest(StrictRequestModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    definition: RubricDefinitionInput

    @field_validator("name", "description")
    @classmethod
    def _strip_name(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return None
        value = normalize_user_text(v, field_name="評分規準名稱")
        if info.field_name == "name" and not value:
            raise ValueError("評分規準名稱不可空白")
        return value or None


class RubricVersionUpdateRequest(StrictRequestModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    definition: RubricDefinitionInput

    @field_validator("name", "description")
    @classmethod
    def _strip_optional_name(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return None
        value = normalize_user_text(v, field_name="評分規準名稱")
        if info.field_name == "name" and not value:
            raise ValueError("評分規準名稱不可空白")
        return value or None


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


class GradeCreateRequest(StrictRequestModel):
    ratings: Dict[Annotated[str, Field(max_length=128)], int] = Field(min_length=1, max_length=100)
    final_score: float = Field(ge=0, le=100)
    teacher_comment: str = Field(min_length=1, max_length=10000)
    teacher_feedback: str = Field(min_length=1, max_length=10000)
    change_reason: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("teacher_comment", "teacher_feedback")
    @classmethod
    def _strip_grade_text(cls, v: str) -> str:
        value = normalize_user_text(v, field_name="評語與回饋")
        if not value:
            raise ValueError("評語與回饋不可空白")
        return value

    @field_validator("change_reason")
    @classmethod
    def _normalize_change_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_user_text(value, field_name="變更原因") or None


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

class ResetPasswordRequest(StrictRequestModel):
    new_password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)
    admin_password: str = Field(min_length=1, max_length=256)

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return validate_password(v)


class LegalAcknowledgementRequest(StrictRequestModel):
    privacy_notice_version: str = Field(min_length=1, max_length=32)
    privacy_acknowledged: bool
    system_terms_version: str = Field(min_length=1, max_length=32)
    terms_accepted: bool


class ChangePasswordRequest(StrictRequestModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=PASSWORD_MAX_LEN)
    legal_acknowledgement: Optional[LegalAcknowledgementRequest] = None

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return validate_password(v)


class MessageResponse(BaseModel):
    message: str


class DeleteConfirmRequest(StrictRequestModel):
    admin_password: str = Field(min_length=1, max_length=256)


class SubmissionRewindRequest(StrictRequestModel):
    admin_password: str = Field(min_length=1, max_length=256)
    target_stage: int = Field(ge=1, le=8)


class LateDeadlineRequest(StrictRequestModel):
    admin_password: str = Field(min_length=1, max_length=256)
    late_deadline: Optional[datetime] = None


class BatchLateDeadlineRequest(StrictRequestModel):
    admin_password: str = Field(min_length=1, max_length=256)
    user_ids: List[int] = Field(min_length=1, max_length=500)
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


# ── Login unfreeze ───────────────────────────────────────────────────────────

class LoginUnfreezeResponse(BaseModel):
    unlocked_accounts: int
    reset_failure_counts: int
    message: str


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
