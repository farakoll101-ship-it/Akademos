from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from typing import Optional, List, Literal
import re
from enum import Enum
from datetime import datetime

PATTERN = r"^(?!.* )(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9])(?!.*[^\x00-\x7F]).{6,18}$"
class RoleEnum(str, Enum):
    Tutor = "t"
    Student = "s"
class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.fullmatch(PATTERN, v):
            raise ValueError(
                "Пароль должен быть 6-18 символов, "
                "содержать заглавные и строчные латинские буквы, цифры "
                "и хотя бы один специальный символ (ASCII, без пробела)"
            )
        return v
    full_name: str
    role: RoleEnum

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    role: RoleEnum

class SubjectEnum(str, Enum):
    Russian = "Russian"
    Literature = "Literature"
    Mathematics = "Mathematics"
    History = "History"
    Social = "Social"
    Biology = "Biology"
    Geography = "Geography"
    Physics = "Physics"
    Chemistry = "Chemistry"
    English = "English"
    Informatics = "informatics"

class SubjectAdd(BaseModel):
    subjects: List[SubjectEnum]

class StudentAdd(BaseModel):
    id_tutor: int
    subject: SubjectEnum
class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class ProfileResponse(BaseModel):
    full_name: str
    email: EmailStr
    role: str
    user_id: int
    photo: Optional[str] = None
    subjects: Optional[List[str]] = None

    model_config = ConfigDict(from_attributes=True)

# Для месяца (краткая информация)
class TimesheetMonthEntry(BaseModel):
    session_name: str
    start_time: datetime
    end_time: datetime
    status: str               # 'p', 'f', 'c', 'd'

# Для дня/недели (полная информация)
class TimesheetFullEntry(BaseModel):
    session_name: str
    start_time: datetime
    end_time: datetime
    status: str
    subject: str
    group_name: str
    has_homework: bool

class DayTimesheet(BaseModel):
    date: str                 # YYYY-MM-DD
    events: List[TimesheetFullEntry]

class WeekTimesheet(BaseModel):
    start_date: str
    end_date: str
    events: List[TimesheetFullEntry]

class MonthTimesheet(BaseModel):
    month: str                # YYYY-MM
    events: List[TimesheetMonthEntry]

# ---------- Схемы для заданий (tasks) ----------
class TaskBase(BaseModel):
    description: str
    type_tasks: Literal["t", "p"]
    max_point: int

class TaskCreate(TaskBase):
    correct_answers: Optional[List[dict]] = None  # для типа "t": [{"point": 1, "answer": "..."}, ...]
    attachments_count: Optional[int] = 0
    
class TaskGroupCreate(BaseModel):
    session_id: int
    name_tgr: str
    deadline: datetime
    tasks: List[TaskCreate]

# Ответ для списка групп заданий (дашборд)
class TaskGroupSummary(BaseModel):
    task_group_id: int
    task_group_name: str
    session_name: str
    subject: str
    deadline: datetime
    total_tasks: int
    status: Literal["unfinished", "completed", "overdue"]   # статус для студента
    earned_points: Optional[int] = None
    max_points: Optional[int] = None
    verification_status: Optional[Literal["verified", "pending"]] = None   # для репетитора

# Для студента
class StudentTaskGroupSummary(TaskGroupSummary):
    pass

# Для репетитора (с привязкой к ученику)
class TutorTaskGroupSummary(TaskGroupSummary):
    student_id: int
    student_name: str

class ExistingTaskGroupInfo(BaseModel):
    task_group_id: int
    task_group_name: str
    session_name: str
    session_date: datetime

# Детальная информация по одному заданию
class TaskDetailResponse(BaseModel):
    task_id: int
    description: str
    type_tasks: str
    max_point: int
    # Поля, заполняемые, если студент уже ответил
    student_answer: Optional[str] = None
    earned_points: Optional[int] = None
    comment: Optional[str] = None
    # Файлы (пути)
    condition_files: List[str] = []      # фото условия
    answer_files: List[str] = []         # фото ответа студента
    comment_files: List[str] = []        # фото комментария репетитора
    # Для репетитора – данные ученика
    student_id: Optional[int] = None
    student_name: Optional[str] = None

# Для создания сессии (занятия)
class SessionCreate(BaseModel):
    name_session: str
    session_date_start: datetime
    session_date_end: datetime
    id_group: int

# Для ответа GET /tasks/create
class SessionInfo(BaseModel):
    id_session: int
    name_session: str
    session_date_start: datetime
    session_date_end: datetime
    group_name: str
    group_id: int

class ExistingTaskGroupInfo(BaseModel):
    task_group_id: int
    session_name: str
    session_date: datetime

# --- новые схемы для групп и индивидуальных учеников ---
class TutorGroupOut(BaseModel):
    id_group: int
    group_name: str
    subject: str
    student_count: int

class IndividualStudentOut(BaseModel):
    id_student: int
    full_name: str
    photo: Optional[str]
    subject: str

class StudentInGroupOut(BaseModel):
    id_student: int
    full_name: str
    photo: Optional[str]

class GroupDetailOut(BaseModel):
    group_name: str
    subject: str
    students: List[StudentInGroupOut]
    available_students: List[StudentInGroupOut]

class CreateGroupRequest(BaseModel):
    group_name: str
    subject: SubjectEnum

class TutorForStudentOut(BaseModel):
    id_tutor: int
    full_name: str
    subjects: List[str]

class AddStudentByCodeRequest(BaseModel):
    code: str   # tutor_123_Mathematics или group_456

class AddStudentToGroupRequest(BaseModel):
    group_id: int

class StudentStatistics(BaseModel):
    attendance_percent: float
    tasks_solved_percent: float
    homeworks_submitted_percent: float
    max_score_homeworks_percent: float