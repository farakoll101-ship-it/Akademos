from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File, Form
from sqlalchemy.orm import Session
from app import schemas
from app.models import models
from app.models.models import User, Tutor, Student, Group, GroupMember, Session, TaskGroup, Task, StudentAnswer, TutorSubject
from app.models.database import get_db
from app.security import (
    create_access_token, create_refresh_token, set_token_cookies,
    get_user_id_from_cookies, get_current_tutor, get_current_student
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Union
import shutil
from datetime import datetime, date, timedelta
from typing import Optional, List
from collections import defaultdict
from app.schemas import (
    StudentTaskGroupSummary, TutorTaskGroupSummary, TaskDetailResponse,
    TimesheetMonthEntry, TimesheetFullEntry, DayTimesheet, WeekTimesheet, MonthTimesheet,
    TutorGroupOut, IndividualStudentOut, GroupDetailOut, CreateGroupRequest,
    TutorForStudentOut, AddStudentByCodeRequest, AddStudentToGroupRequest,
    SubjectEnum, StudentInGroupOut, StudentStatistics,ProfileResponse
)

def compute_student_statistics(student_id: int, db: Session, subject: Optional[str] = None) -> dict:
    # Группы студента
    groups_query = db.query(Group).join(GroupMember, GroupMember.id_group == Group.id_group).filter(
        GroupMember.id_student == student_id
    )
    if subject:
        groups_query = groups_query.filter(Group.subjects == subject)
    groups = groups_query.all()
    group_ids = [g.id_group for g in groups]
    if not group_ids:
        return {
            "attendance_percent": 0.0,
            "points_earned_percent": 0.0,
            "homeworks_submitted_percent": 0.0,
            "max_score_homeworks_percent": 0.0,
        }

    # Сессии
    sessions = db.query(Session).filter(Session.id_group.in_(group_ids)).all()
    total_sessions = len(sessions)
    attended_sessions = sum(1 for s in sessions if s.status == 'f')
    attendance_percent = (attended_sessions / total_sessions * 100) if total_sessions else 0.0

    # Группы заданий
    task_groups = db.query(TaskGroup).join(Session, Session.id_session == TaskGroup.id_session).filter(
        Session.id_group.in_(group_ids)
    ).all()
    total_task_groups = len(task_groups)

    # Все задачи
    task_ids = []
    task_group_map = {}
    for tg in task_groups:
        tasks = db.query(Task).filter(Task.id_t_gr == tg.id_t_gr).all()
        task_ids.extend(t.task_id for t in tasks)
        task_group_map[tg.id_t_gr] = tasks

    # Ответы студента
    answers = db.query(StudentAnswer).filter(
        StudentAnswer.id_student == student_id,
        StudentAnswer.task_id.in_(task_ids) if task_ids else False
    ).all()
    answer_by_task = {a.task_id: a for a in answers}

    # Считаем набранные и максимальные баллы ТОЛЬКО по проверенным (status 'v')
    earned_sum = 0
    max_sum = 0
    for task_id in task_ids:
        task = db.query(Task).filter(Task.task_id == task_id).first()
        if not task:
            continue
        max_sum += task.max_point
        ans = answer_by_task.get(task_id)
        if ans and ans.status_ta == 'v' and ans.is_point is not None:
            earned_sum += ans.is_point
    points_earned_percent = (earned_sum / max_sum * 100) if max_sum else 0.0

    # Анализ групп заданий: сдана (все ответы есть и статус не 'u') и максимальный балл
    submitted_count = 0
    max_score_count = 0
    for tg_id, tasks in task_group_map.items():
        all_submitted = all(
            task.task_id in answer_by_task and answer_by_task[task.task_id].status_ta in ('c', 'v')
            for task in tasks
        )
        if all_submitted:
            submitted_count += 1
            all_verified = all(
                task.task_id in answer_by_task and answer_by_task[task.task_id].status_ta == 'v'
                for task in tasks
            )
            if all_verified:
                total_earned = sum(answer_by_task[task.task_id].is_point or 0 for task in tasks if task.task_id in answer_by_task)
                total_max = sum(task.max_point for task in tasks)
                if total_earned == total_max:
                    max_score_count += 1

    homeworks_submitted_percent = (submitted_count / total_task_groups * 100) if total_task_groups else 0.0
    max_score_homeworks_percent = (max_score_count / total_task_groups * 100) if total_task_groups else 0.0

    return {
        "attendance_percent": round(attendance_percent, 2),
        "points_earned_percent": round(points_earned_percent, 2),
        "homeworks_submitted_percent": round(homeworks_submitted_percent, 2),
        "max_score_homeworks_percent": round(max_score_homeworks_percent, 2),
    }

def save_file(file: UploadFile, target_dir: Path, prefix: str, ext: str) -> str:
    """Сохраняет файл и возвращает относительный путь"""
    filename = f"{prefix}{ext}"
    filepath = target_dir / filename
    with filepath.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return f"{target_dir.name}/{filename}"

app = FastAPI(title="Akademos API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://111.88.156.119:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Папки для файлов
PROFILE_PIC_DIR = Path(__file__).parent.parent / "profilepic"
DESCRIPTION_PIC_DIR = Path(__file__).parent.parent / "descriptionpic"
ANSWER_PIC_DIR = Path(__file__).parent.parent / "answerpic"
COMMENT_PIC_DIR = Path(__file__).parent.parent / "commentspic"

DESCRIPTION_PIC_DIR.mkdir(exist_ok=True)
ANSWER_PIC_DIR.mkdir(exist_ok=True)
COMMENT_PIC_DIR.mkdir(exist_ok=True)
PROFILE_PIC_DIR.mkdir(exist_ok=True)

app.mount("/descriptionpic", StaticFiles(directory=str(DESCRIPTION_PIC_DIR)), name="descriptionpic")
app.mount("/answerpic", StaticFiles(directory=str(ANSWER_PIC_DIR)), name="answerpic")
app.mount("/commentspic", StaticFiles(directory=str(COMMENT_PIC_DIR)), name="commentspic")
app.mount("/profilepic", StaticFiles(directory=str(PROFILE_PIC_DIR)), name="profilepic")

@app.post("/login", response_model=schemas.UserOut)
def login(
    credentials: schemas.UserLogin,
    response: Response,
    db: Session = Depends(get_db)
):
    # Ищем пользователя по email
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    # Проверяем пароль (временно – прямое сравнение, необходимо хеширование!)
    if user.password != credentials.password:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    # Сверяем роль (если важна)
    if user.role != credentials.role.value:
        raise HTTPException(status_code=403, detail="Роль не совпадает с учётной записью")

    # Генерируем токены и ставим куки
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})
    set_token_cookies(response, access_token, refresh_token)

    return user

@app.get("/users/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user

@app.post("/users/", response_model=schemas.UserOut, status_code=201)
def create_user(
    user_data: schemas.UserCreate,
    response: Response,
    db: Session = Depends(get_db)
):
    # Проверяем, не занят ли email
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Создаём пользователя
    db_user = User(**user_data.model_dump())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # В зависимости от роли создаём запись в tutors или students
    if user_data.role == schemas.RoleEnum.Tutor:   # "t"
        tutor = Tutor(id=db_user.id)  # id - внешний ключ на users.id
        db.add(tutor)
        db.commit()
        # не нужно refresh, так как id_tutor сгенерируется автоматически
    elif user_data.role == schemas.RoleEnum.Student:   # "s"
        student = Student(id=db_user.id)
        db.add(student)
        db.commit()

    # Генерируем токены и ставим куки
    access_token = create_access_token(data={"sub": db_user.id})
    refresh_token = create_refresh_token(data={"sub": db_user.id})
    set_token_cookies(response, access_token, refresh_token)

    return db_user


@app.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db)
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.administrator:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete user because they are an administrator. Remove administrator role first."
        )
    if user.tutor:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete user because they are a tutor. Remove tutor role first."
        )
    if user.student:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete user because they are a student. Remove student role first."
        )

    db.delete(user)
    db.commit()


@app.post("/me/subjects", status_code=201)
def add_tutor_subjects(
        subjects_data: schemas.SubjectAdd,
        request: Request,
        db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)

    # Исправлено: filter(models.Tutor.id == user_id)
    tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(status_code=403, detail="Только репетитор может добавлять предметы")

    added = []
    for subject_enum in subjects_data.subjects:
        existing = db.query(models.TutorSubject).filter(
            models.TutorSubject.id_tutor == tutor.id_tutor,
            models.TutorSubject.subject_name == subject_enum.value
        ).first()
        if existing:
            continue
        tutor_subject = models.TutorSubject(
            id_tutor=tutor.id_tutor,
            subject_name=subject_enum.value
        )
        db.add(tutor_subject)
        added.append(subject_enum.value)

    db.commit()
    return {"message": f"Добавлены предметы: {added}"}

@app.get("/subjects")
def get_all_subjects():
    """Возвращает список всех возможных предметов"""
    return {
        "subjects": [
            {"id": "Math", "name": "Математика"},
            {"id": "Russian", "name": "Русский язык"},
            {"id": "English", "name": "Английский язык"},
            {"id": "Physics", "name": "Физика"},
            {"id": "Chemistry", "name": "Химия"},
            {"id": "History", "name": "История"},
            {"id": "Biology", "name": "Биология"},
            {"id": "Informatics", "name": "Информатика"},
            {"id": "Social", "name": "Обществознание"},
            {"id": "Literature", "name": "Литература"},
            {"id": "Geography", "name": "География"}
        ]
    }

@app.post("/students/add", status_code=200)
def student_bind_to_tutor(
    data: schemas.StudentAdd,   # теперь содержит id_tutor + subject
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)

    # 1. Проверяем, что текущий пользователь – студент
    student = db.query(models.Student).filter(models.Student.id == user_id).first()
    if not student:
        raise HTTPException(status_code=403, detail="Только студент может привязаться к преподавателю")

    # 2. Находим репетитора по id_tutor (первичный ключ tutors.id_tutor)
    tutor = db.query(models.Tutor).filter(models.Tutor.id_tutor == data.id_tutor).first()
    if not tutor:
        raise HTTPException(status_code=404, detail="Преподаватель не найден")

    # 3. Проверяем, что репетитор действительно ведёт указанный предмет
    teaches_subject = db.query(models.TutorSubject).filter(
        models.TutorSubject.id_tutor == tutor.id_tutor,
        models.TutorSubject.subject_name == data.subject.value
    ).first()
    if not teaches_subject:
        raise HTTPException(status_code=400, detail=f"Преподаватель не ведёт предмет {data.subject.value}")

    # 4. Проверяем, нет ли у студента уже репетитора по такому же предмету
    existing_group_with_subject = db.query(models.Group).join(
        models.GroupMember, models.GroupMember.id_group == models.Group.id_group
    ).filter(
        models.GroupMember.id_student == student.id_student,
        models.Group.subjects == data.subject.value
    ).first()
    if existing_group_with_subject:
        raise HTTPException(status_code=409, detail=f"У студента уже есть преподаватель по предмету {data.subject.value}")

    # 5. Создаём новую группу (для данного студента, репетитора и предмета)
    new_group = models.Group(
        subjects=data.subject.value,      # сохраняем название предмета
        id_tutor=tutor.id_tutor
    )
    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    # 6. Добавляем студента в группу
    group_member = models.GroupMember(
        id_group=new_group.id_group,
        id_student=student.id_student
    )
    db.add(group_member)
    db.commit()

    return {
        "message": "Студент успешно привязан к преподавателю",
        "tutor_id": data.id_tutor,
        "subject": data.subject.value,
        "group_id": new_group.id_group
    }

@app.post("/profile/picture")
async def upload_profile_picture(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Получаем текущего пользователя
    user_id = get_user_id_from_cookies(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Проверяем расширение файла
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(400, "Неподдерживаемый формат. Используйте JPG, PNG, GIF, WEBP.")

    # Генерируем имя файла: {user_id}.расширение
    new_filename = f"{user_id}{file_ext}"
    file_path = PROFILE_PIC_DIR / new_filename

    # Удаляем старый файл, если он существует
    if file_path.exists():
        file_path.unlink()

    # Сохраняем новый файл
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception:
        raise HTTPException(500, "Ошибка сохранения файла")

    # Сохраняем путь в БД (относительный, для статической раздачи)
    relative_path = f"profilepic/{new_filename}"
    user.path_profile_pic = relative_path
    db.commit()

    return {
        "message": "Фото профиля обновлено",
        "photo_url": f"/{relative_path}"
    }

@app.get("/profile", response_model=ProfileResponse)
def get_profile(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Базовые данные
    profile_data = {
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "user_id": user.id,
        "photo": user.path_profile_pic,
    }

    # Если репетитор – добавляем предметы
    if user.role == "t":   # "t" = Tutor
        tutor = db.query(Tutor).filter(Tutor.id == user.id).first()
        if tutor:
            subjects = db.query(TutorSubject.subject_name).filter(
                TutorSubject.id_tutor == tutor.id_tutor
            ).all()
            profile_data["subjects"] = [s.subject_name for s in subjects]
        else:
            profile_data["subjects"] = []
    else:
        pass

    # Возвращаем объект, который Pydantic провалидирует как ProfileResponse
    return profile_data

@app.get("/timesheet/day/{date_str}", response_model=DayTimesheet)
def get_timesheet_day(
    date_str: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты, используйте YYYY-MM-DD")

    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    end_dt = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, 999999)

    events = []

    if user.role == "t":   # Репетитор
        tutor = db.query(models.Tutor).filter(models.Tutor.id == user.id).first()
        if not tutor:
            raise HTTPException(status_code=404, detail="Репетитор не найден")
        groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
        group_ids = [g.id_group for g in groups]
        group_map = {g.id_group: g for g in groups}

        # Сессии
        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_dt,
            models.Session.session_date_start <= end_dt
        ).order_by(models.Session.session_date_start).all()

        for sess in sessions:
            group = group_map.get(sess.id_group)
            if not group:
                continue
            has_hw = db.query(models.Task).join(
                models.TaskGroup, models.TaskGroup.id_t_gr == models.Task.id_t_gr
            ).filter(models.TaskGroup.id_session == sess.id_session).first() is not None

            events.append(TimesheetFullEntry(
                session_name=sess.name_session,
                start_time=sess.session_date_start,
                end_time=sess.session_date_end,
                status=sess.status,
                subject=group.subjects,
                group_name=group.group_name,
                has_homework=has_hw
            ))

        # Дедлайны
        task_groups = db.query(models.TaskGroup).join(
            models.Session, models.Session.id_session == models.TaskGroup.id_session
        ).filter(
            models.Session.id_group.in_(group_ids),
            models.TaskGroup.deadline >= start_dt,
            models.TaskGroup.deadline <= end_dt
        ).all()
        for tg in task_groups:
            group = group_map.get(tg.session.id_group)
            events.append(TimesheetFullEntry(
                session_name=tg.session.name_session,
                start_time=tg.deadline,
                end_time=tg.deadline,
                status="d",
                subject=group.subjects if group else "",
                group_name=group.group_name if group else "",
                has_homework=True
            ))

    else:   # Студент
        student = db.query(models.Student).filter(models.Student.id == user.id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Студент не найден")
        groups = db.query(models.Group).join(
            models.GroupMember, models.GroupMember.id_group == models.Group.id_group
        ).filter(models.GroupMember.id_student == student.id_student).all()
        group_ids = [g.id_group for g in groups]
        group_map = {g.id_group: g for g in groups}

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_dt,
            models.Session.session_date_start <= end_dt
        ).order_by(models.Session.session_date_start).all()

        for sess in sessions:
            group = group_map.get(sess.id_group)
            has_hw = db.query(models.Task).join(
                models.TaskGroup, models.TaskGroup.id_t_gr == models.Task.id_t_gr
            ).filter(models.TaskGroup.id_session == sess.id_session).first() is not None

            events.append(TimesheetFullEntry(
                session_name=sess.name_session,
                start_time=sess.session_date_start,
                end_time=sess.session_date_end,
                status=sess.status,
                subject=group.subjects if group else "",
                group_name=group.group_name if group else "",
                has_homework=has_hw
            ))

        task_groups = db.query(models.TaskGroup).join(
            models.Session, models.Session.id_session == models.TaskGroup.id_session
        ).filter(
            models.Session.id_group.in_(group_ids),
            models.TaskGroup.deadline >= start_dt,
            models.TaskGroup.deadline <= end_dt
        ).all()
        for tg in task_groups:
            group = group_map.get(tg.session.id_group)
            events.append(TimesheetFullEntry(
                session_name=tg.session.name_session,
                start_time=tg.deadline,
                end_time=tg.deadline,
                status="d",
                subject=group.subjects if group else "",
                group_name=group.group_name if group else "",
                has_homework=True
            ))

    events.sort(key=lambda x: x.start_time)
    return DayTimesheet(date=date_str, events=events)

@app.get("/timesheet/week/{date_str}", response_model=WeekTimesheet)
def get_timesheet_week(
    date_str: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты, используйте YYYY-MM-DD")

    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Календарная неделя: понедельник - воскресенье
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    start_dt = datetime(start_of_week.year, start_of_week.month, start_of_week.day, 0, 0, 0)
    end_dt = datetime(end_of_week.year, end_of_week.month, end_of_week.day, 23, 59, 59, 999999)

    events = []

    if user.role == "t":
        tutor = db.query(models.Tutor).filter(models.Tutor.id == user.id).first()
        if not tutor:
            raise HTTPException(status_code=404, detail="Репетитор не найден")
        groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
        group_ids = [g.id_group for g in groups]
        group_map = {g.id_group: g for g in groups}

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_dt,
            models.Session.session_date_start <= end_dt
        ).order_by(models.Session.session_date_start).all()

        for sess in sessions:
            group = group_map.get(sess.id_group)
            has_hw = db.query(models.Task).join(
                models.TaskGroup, models.TaskGroup.id_t_gr == models.Task.id_t_gr
            ).filter(models.TaskGroup.id_session == sess.id_session).first() is not None

            events.append(TimesheetFullEntry(
                session_name=sess.name_session,
                start_time=sess.session_date_start,
                end_time=sess.session_date_end,
                status=sess.status,
                subject=group.subjects,
                group_name=group.group_name,
                has_homework=has_hw
            ))

        task_groups = db.query(models.TaskGroup).join(
            models.Session, models.Session.id_session == models.TaskGroup.id_session
        ).filter(
            models.Session.id_group.in_(group_ids),
            models.TaskGroup.deadline >= start_dt,
            models.TaskGroup.deadline <= end_dt
        ).all()
        for tg in task_groups:
            group = group_map.get(tg.session.id_group)
            events.append(TimesheetFullEntry(
                session_name=tg.session.name_session,
                start_time=tg.deadline,
                end_time=tg.deadline,
                status="d",
                subject=group.subjects if group else "",
                group_name=group.group_name if group else "",
                has_homework=True
            ))

    else:
        student = db.query(models.Student).filter(models.Student.id == user.id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Студент не найден")
        groups = db.query(models.Group).join(
            models.GroupMember, models.GroupMember.id_group == models.Group.id_group
        ).filter(models.GroupMember.id_student == student.id_student).all()
        group_ids = [g.id_group for g in groups]
        group_map = {g.id_group: g for g in groups}

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_dt,
            models.Session.session_date_start <= end_dt
        ).order_by(models.Session.session_date_start).all()

        for sess in sessions:
            group = group_map.get(sess.id_group)
            has_hw = db.query(models.Task).join(
                models.TaskGroup, models.TaskGroup.id_t_gr == models.Task.id_t_gr
            ).filter(models.TaskGroup.id_session == sess.id_session).first() is not None

            events.append(TimesheetFullEntry(
                session_name=sess.name_session,
                start_time=sess.session_date_start,
                end_time=sess.session_date_end,
                status=sess.status,
                subject=group.subjects if group else "",
                group_name=group.group_name if group else "",
                has_homework=has_hw
            ))

        task_groups = db.query(models.TaskGroup).join(
            models.Session, models.Session.id_session == models.TaskGroup.id_session
        ).filter(
            models.Session.id_group.in_(group_ids),
            models.TaskGroup.deadline >= start_dt,
            models.TaskGroup.deadline <= end_dt
        ).all()
        for tg in task_groups:
            group = group_map.get(tg.session.id_group)
            events.append(TimesheetFullEntry(
                session_name=tg.session.name_session,
                start_time=tg.deadline,
                end_time=tg.deadline,
                status="d",
                subject=group.subjects if group else "",
                group_name=group.group_name if group else "",
                has_homework=True
            ))

    events.sort(key=lambda x: x.start_time)
    return WeekTimesheet(
        start_date=start_of_week.isoformat(),
        end_date=end_of_week.isoformat(),
        events=events
    )

@app.get("/timesheet/month/{date_str}", response_model=MonthTimesheet)
def get_timesheet_month(
    date_str: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        target_date = date.fromisoformat(date_str)
        year = target_date.year
        month = target_date.month
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты, используйте YYYY-MM-DD")

    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    start_of_month = datetime(year, month, 1, 0, 0, 0)
    next_month = start_of_month + timedelta(days=32)
    end_of_month = next_month.replace(day=1) - timedelta(microseconds=1)

    events = []

    if user.role == "t":
        tutor = db.query(models.Tutor).filter(models.Tutor.id == user.id).first()
        if not tutor:
            raise HTTPException(status_code=404, detail="Репетитор не найден")
        groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
        group_ids = [g.id_group for g in groups]

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_of_month,
            models.Session.session_date_start <= end_of_month
        ).order_by(models.Session.session_date_start).all()

        for sess in sessions:
            events.append(TimesheetMonthEntry(
                session_name=sess.name_session,
                start_time=sess.session_date_start,
                end_time=sess.session_date_end,
                status=sess.status
            ))

        task_groups = db.query(models.TaskGroup).join(
            models.Session, models.Session.id_session == models.TaskGroup.id_session
        ).filter(
            models.Session.id_group.in_(group_ids),
            models.TaskGroup.deadline >= start_of_month,
            models.TaskGroup.deadline <= end_of_month
        ).all()
        for tg in task_groups:
            events.append(TimesheetMonthEntry(
                session_name=tg.session.name_session,
                start_time=tg.deadline,
                end_time=tg.deadline,
                status="d"
            ))

    else:
        student = db.query(models.Student).filter(models.Student.id == user.id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Студент не найден")
        groups = db.query(models.Group).join(
            models.GroupMember, models.GroupMember.id_group == models.Group.id_group
        ).filter(models.GroupMember.id_student == student.id_student).all()
        group_ids = [g.id_group for g in groups]

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_of_month,
            models.Session.session_date_start <= end_of_month
        ).order_by(models.Session.session_date_start).all()

        for sess in sessions:
            events.append(TimesheetMonthEntry(
                session_name=sess.name_session,
                start_time=sess.session_date_start,
                end_time=sess.session_date_end,
                status=sess.status
            ))

        task_groups = db.query(models.TaskGroup).join(
            models.Session, models.Session.id_session == models.TaskGroup.id_session
        ).filter(
            models.Session.id_group.in_(group_ids),
            models.TaskGroup.deadline >= start_of_month,
            models.TaskGroup.deadline <= end_of_month
        ).all()
        for tg in task_groups:
            events.append(TimesheetMonthEntry(
                session_name=tg.session.name_session,
                start_time=tg.deadline,
                end_time=tg.deadline,
                status="d"
            ))

    events.sort(key=lambda x: x.start_time)
    return MonthTimesheet(month=f"{year:04d}-{month:02d}", events=events)

@app.post("/timesheet/day", status_code=201)
def create_session(
    session_data: schemas.SessionCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только репетитор может создавать занятия")

    tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(404, "Репетитор не найден")

    # Проверяем группу
    group = db.query(models.Group).filter(
        models.Group.id_group == session_data.id_group,
        models.Group.id_tutor == tutor.id_tutor
    ).first()
    if not group:
        raise HTTPException(404, "Группа не найдена или не принадлежит вам")

    if session_data.session_date_start >= session_data.session_date_end:
        raise HTTPException(400, "Время начала должно быть меньше времени окончания")

    new_session = models.Session(
        name_session=session_data.name_session,
        id_group=group.id_group,
        session_date_start=session_data.session_date_start,
        session_date_end=session_data.session_date_end,
        status="p"   # planned
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    return {
        "message": "Занятие создано",
        "session_id": new_session.id_session,
        "session_name": new_session.name_session,
        "group_id": group.id_group,
        "group_name": group.group_name
    }


@app.get("/sessions/date/{date_str}")
def get_sessions_by_date(
        date_str: str,
        request: Request,
        db: Session = Depends(get_db)
):
    """Получить все занятия на конкретную дату"""
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()

    target_date = datetime.fromisoformat(date_str)
    start_of_day = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

    if user.role == "t":  # репетитор
        tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
        groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
        group_ids = [g.id_group for g in groups]

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_of_day,
            models.Session.session_date_start <= end_of_day
        ).all()
    else:  # студент
        student = db.query(models.Student).filter(models.Student.id == user_id).first()
        groups = db.query(models.Group).join(
            models.GroupMember
        ).filter(models.GroupMember.id_student == student.id_student).all()
        group_ids = [g.id_group for g in groups]

        sessions = db.query(models.Session).filter(
            models.Session.id_group.in_(group_ids),
            models.Session.session_date_start >= start_of_day,
            models.Session.session_date_start <= end_of_day
        ).all()

    return {
        "date": date_str,
        "sessions": [
            {
                "id": s.id_session,
                "name": s.name_session,
                "start": s.session_date_start.isoformat(),
                "end": s.session_date_end.isoformat(),
                "status": s.status,
                "group_id": s.id_group
            }
            for s in sessions
        ]
    }


@app.delete("/sessions/{session_id}")
def delete_session(
        session_id: int,
        request: Request,
        db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()

    if user.role != "t":
        raise HTTPException(403, "Только репетитор может удалять занятия")

    session = db.query(models.Session).filter(models.Session.id_session == session_id).first()
    if not session:
        raise HTTPException(404, "Занятие не найдено")

    db.delete(session)
    db.commit()

    return {"message": "Занятие удалено"}

@app.get("/tasks", response_model=List[Union[StudentTaskGroupSummary, TutorTaskGroupSummary]])
def get_task_groups(
    request: Request,
    group_name: Optional[str] = None,
    subjects: Optional[str] = None,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    result = []

    if user.role == "t":   # Репетитор
        tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
        if not tutor:
            raise HTTPException(404, "Репетитор не найден")
        # Все группы репетитора
        groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor)
        if group_name:
            groups = groups.filter(models.Group.group_name == group_name)
        if subjects:
            groups = groups.filter(models.Group.subjects == subjects)
        groups = groups.all()

        # Для каждого ученика в каждой группе собираем его TaskGroup
        for grp in groups:
            members = db.query(models.GroupMember).filter(models.GroupMember.id_group == grp.id_group).all()
            for member in members:
                student = db.query(models.Student).filter(models.Student.id_student == member.id_student).first()
                if not student:
                    continue
                user_student = db.query(models.User).filter(models.User.id == student.id).first()
                # TaskGroup'ы, связанные с группой через сессии
                task_groups = db.query(models.TaskGroup).join(
                    models.Session, models.Session.id_session == models.TaskGroup.id_session
                ).filter(models.Session.id_group == grp.id_group).all()
                for tg in task_groups:
                    # Статус для студента по этой TaskGroup
                    tasks = db.query(models.Task).filter(models.Task.id_t_gr == tg.id_t_gr).all()
                    student_answers = db.query(models.StudentAnswer).filter(
                        models.StudentAnswer.id_student == student.id_student,
                        models.StudentAnswer.task_id.in_([t.task_id for t in tasks])
                    ).all()
                    # Подсчёт баллов
                    total_max = sum(t.max_point for t in tasks)
                    earned = sum(sa.is_point for sa in student_answers if sa.is_point is not None)
                    all_answered = all(sa.status_ta in ('c', 'v') for sa in student_answers)
                    now = datetime.utcnow()
                    if not all_answered and tg.deadline < now:
                        status = "overdue"
                    elif all_answered:
                        status = "completed"
                    else:
                        status = "unfinished"
                    verified = all(sa.status_ta == 'v' for sa in student_answers) if student_answers else False
                    result.append(TutorTaskGroupSummary(
                        task_group_id=tg.id_t_gr,
                        task_group_name=tg.name_tgr,
                        session_name=tg.session.name_session,
                        subject=grp.subjects,
                        deadline=tg.deadline,
                        total_tasks=len(tasks),
                        status=status,
                        earned_points=earned,
                        max_points=total_max,
                        verification_status="verified" if verified else "pending",
                        student_id=user_student.id,
                        student_name=user_student.full_name
                    ))
    else:   # Студент
        student = db.query(models.Student).filter(models.Student.id == user_id).first()
        if not student:
            raise HTTPException(404, "Студент не найден")
        # Группы студента
        groups = db.query(models.Group).join(
            models.GroupMember, models.GroupMember.id_group == models.Group.id_group
        ).filter(models.GroupMember.id_student == student.id_student)
        if group_name:
            groups = groups.filter(models.Group.group_name == group_name)
        if subjects:
            groups = groups.filter(models.Group.subjects == subjects)
        groups = groups.all()

        for grp in groups:
            task_groups = db.query(models.TaskGroup).join(
                models.Session, models.Session.id_session == models.TaskGroup.id_session
            ).filter(models.Session.id_group == grp.id_group).all()
            for tg in task_groups:
                tasks = db.query(models.Task).filter(models.Task.id_t_gr == tg.id_t_gr).all()
                student_answers = db.query(models.StudentAnswer).filter(
                    models.StudentAnswer.id_student == student.id_student,
                    models.StudentAnswer.task_id.in_([t.task_id for t in tasks])
                ).all()
                total_max = sum(t.max_point for t in tasks)
                earned = sum(sa.is_point for sa in student_answers if sa.is_point is not None)
                all_answered = all(sa.status_ta in ('c', 'v') for sa in student_answers)
                now = datetime.utcnow()
                if not all_answered and tg.deadline < now:
                    status = "overdue"
                elif all_answered:
                    status = "completed"
                else:
                    status = "unfinished"
                result.append(StudentTaskGroupSummary(
                    task_group_id=tg.id_t_gr,
                    task_group_name=tg.name_tgr,
                    session_name=tg.session.name_session,
                    subject=grp.subjects,
                    deadline=tg.deadline,
                    total_tasks=len(tasks),
                    status=status,
                    earned_points=earned,
                    max_points=total_max,
                    verification_status=None
                ))

    return result

@app.get("/tasks/{task_group_id}/{task_number}", response_model=TaskDetailResponse)
def get_task_detail(
    task_group_id: int,
    task_number: int,
    request: Request,
    id_student: Optional[int] = None,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    # Находим задание по группе заданий и порядковому номеру (порядок = task_id относительно id_t_gr, но проще добавить поле order_num)
    # В текущей модели нет поля order_num, поэтому используем сортировку по task_id
    tasks = db.query(models.Task).filter(models.Task.id_t_gr == task_group_id).order_by(models.Task.task_id).all()
    if task_number < 1 or task_number > len(tasks):
        raise HTTPException(404, "Задание с таким номером не найдено")
    task = tasks[task_number - 1]

    # Определяем, кто запрашивает
    student_id_for_answer = None
    is_tutor = (user.role == "t")
    if is_tutor:
        if id_student is None:
            # берём первого ученика в алфавитном порядке из группы, привязанной к этой TaskGroup
            # Находим сессию, потом группу, потом учеников
            task_group = db.query(models.TaskGroup).filter(models.TaskGroup.id_t_gr == task_group_id).first()
            session = task_group.session
            group = session.group
            members = db.query(models.GroupMember).filter(models.GroupMember.id_group == group.id_group).join(
                models.Student, models.Student.id_student == models.GroupMember.id_student
            ).join(models.User, models.User.id == models.Student.id).order_by(models.User.full_name).all()
            if not members:
                raise HTTPException(404, "В группе нет учеников")
            student_id_for_answer = members[0].id_student
        else:
            # проверяем, что такой студент есть и он в группе репетитора
            student = db.query(models.Student).filter(models.Student.id == id_student).first()
            if not student:
                raise HTTPException(404, "Студент не найден")
            # дополнительно проверить, что студент в группе репетитора (опустим для краткости)
            student_id_for_answer = student.id_student
    else:
        student = db.query(models.Student).filter(models.Student.id == user_id).first()
        if not student:
            raise HTTPException(404, "Студент не найден")
        student_id_for_answer = student.id_student

    # Ищем ответ студента
    student_answer = db.query(models.StudentAnswer).filter(
        models.StudentAnswer.task_id == task.task_id,
        models.StudentAnswer.id_student == student_id_for_answer
    ).first()

    # Файлы условия
    condition_files = []
    path_descs = db.query(models.PathDescription).filter(models.PathDescription.task_id == task.task_id).all()
    for pd in path_descs:
        condition_files.append(pd.path)

    answer_files = []
    comment_files = []
    student_answer_text = None
    earned_points = None
    comment_text = None
    student_name = None
    student_id_out = None

    if student_answer:
        # Файлы ответа
        path_answers = db.query(models.PathAnswer).filter(models.PathAnswer.answer_id == student_answer.answer_id).all()
        for pa in path_answers:
            answer_files.append(pa.path)
        student_answer_text = student_answer.answer
        earned_points = student_answer.is_point
        # Комментарии
        comment = db.query(models.Comment).filter(models.Comment.answer_id == student_answer.answer_id).first()
        if comment:
            comment_text = comment.comments
            path_comments = db.query(models.PathComment).filter(models.PathComment.id_comments == comment.id_comments).all()
            for pc in path_comments:
                comment_files.append(pc.path_comments)
        # Если репетитор – добавим данные ученика
        if is_tutor:
            student_user = db.query(models.User).filter(models.User.id == student_answer.student.id).first()
            student_name = student_user.full_name
            student_id_out = student_user.id

    return TaskDetailResponse(
        task_id=task.task_id,
        description=task.description,
        type_tasks=task.type_tasks,
        max_point=task.max_point,
        student_answer=student_answer_text,
        earned_points=earned_points,
        comment=comment_text,
        condition_files=condition_files,
        answer_files=answer_files,
        comment_files=comment_files,
        student_id=student_id_out,
        student_name=student_name
    )

@app.post("/tasks/{task_group_id}/{task_number}")
def save_student_answer(
    task_group_id: int,
    task_number: int,
    request: Request,
    answer_text: Optional[str] = Form(None),
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "s":
        raise HTTPException(403, "Только студент может сохранять ответ")

    student = db.query(models.Student).filter(models.Student.id == user_id).first()
    if not student:
        raise HTTPException(404, "Студент не найден")

    # Находим задание по его номеру в группе
    tasks = db.query(models.Task).filter(models.Task.id_t_gr == task_group_id).order_by(models.Task.task_id).all()
    if task_number < 1 or task_number > len(tasks):
        raise HTTPException(404, "Задание с таким номером не найдено")
    task = tasks[task_number - 1]

    # Проверяем, не завершена ли уже эта группа заданий (если у всех заданий статус 'c' или 'v' – завершена)
    all_tasks = db.query(models.Task).filter(models.Task.id_t_gr == task_group_id).all()
    existing_answers = db.query(models.StudentAnswer).filter(
        models.StudentAnswer.id_student == student.id_student,
        models.StudentAnswer.task_id.in_([t.task_id for t in all_tasks])
    ).all()
    # Если все ответы имеют статус 'c' или 'v', то группа завершена – менять нельзя
    if existing_answers and all(a.status_ta in ('c', 'v') for a in existing_answers):
        raise HTTPException(400, "Эта группа заданий уже завершена, нельзя изменить ответ")

    # Ищем или создаём StudentAnswer для этого конкретного задания
    student_answer = db.query(models.StudentAnswer).filter(
        models.StudentAnswer.task_id == task.task_id,
        models.StudentAnswer.id_student == student.id_student
    ).first()
    if not student_answer:
        student_answer = models.StudentAnswer(
            task_id=task.task_id,
            id_student=student.id_student,
            status_ta="u",      # unfinished – по умолчанию
            is_point=None
        )
        db.add(student_answer)
        db.flush()   # чтобы получить answer_id

    # Сохраняем ответ в зависимости от типа задания
    if task.type_tasks == "t":
        if not answer_text:
            raise HTTPException(400, "Для текстового задания требуется answer_text")
        student_answer.answer = answer_text
        # НЕ проверяем правильность, НЕ меняем статус, НЕ выставляем баллы
    else:  # type_tasks == "p"
        if not files:
            raise HTTPException(400, "Для фото-задания требуется загрузить файлы")
        student_answer.answer = "Фото ответа"  # или можно сохранять описание
        # Удаляем старые файлы ответа, если есть
        old_paths = db.query(models.PathAnswer).filter(models.PathAnswer.answer_id == student_answer.answer_id).all()
        for old in old_paths:
            # опционально удалить физические файлы
            db.delete(old)
        # Сохраняем новые файлы
        for idx, file in enumerate(files):
            ext = Path(file.filename).suffix.lower()
            # Генерируем имя: answer_{answer_id}_{idx}.ext
            prefix = f"answer_{student_answer.answer_id}_{idx}"
            rel_path = save_file(file, ANSWER_PIC_DIR, prefix, ext)
            path_answer = models.PathAnswer(path=rel_path, answer_id=student_answer.answer_id)
            db.add(path_answer)

    # Статус оставляем "u" (unfinished)
    student_answer.status_ta = "u"
    db.commit()

    return {"message": "Ответ сохранён (статус unfinished)"}

@app.post("/tasks/{task_group_id}")
def finish_task_group(
    task_group_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "s":
        raise HTTPException(403, "Только студент может завершить группу заданий")

    student = db.query(models.Student).filter(models.Student.id == user_id).first()
    if not student:
        raise HTTPException(404, "Студент не найден")

    # Все задания в этой группе
    tasks = db.query(models.Task).filter(models.Task.id_t_gr == task_group_id).order_by(models.Task.task_id).all()
    if not tasks:
        raise HTTPException(404, "Группа заданий не найдена")

    # Для каждого задания проверяем, есть ли ответ
    for task in tasks:
        student_answer = db.query(models.StudentAnswer).filter(
            models.StudentAnswer.task_id == task.task_id,
            models.StudentAnswer.id_student == student.id_student
        ).first()
        if not student_answer:
            raise HTTPException(400, f"Задание №{tasks.index(task)+1} не имеет сохранённого ответа")
        # Если ответ уже имеет статус 'c' или 'v', пропускаем (уже обработано)
        if student_answer.status_ta in ('c', 'v'):
            continue
        # Если статус 'u' – обрабатываем
        if student_answer.status_ta == "u":
            # Для текстового задания – автопроверка
            if task.type_tasks == "t":
                if not student_answer.answer:
                    raise HTTPException(400, f"В текстовом задании №{tasks.index(task)+1} нет текста ответа")
                # Ищем правильный ответ
                correct_answers = db.query(models.TaskCorrectAnswer).filter(
                    models.TaskCorrectAnswer.task_id == task.task_id
                ).all()
                # Сверяем: можно точное совпадение строки
                earned = 0
                for ca in correct_answers:
                    if ca.correct_answer == student_answer.answer:
                        earned = ca.point
                        break
                student_answer.is_point = earned
                # Для текстовых – сразу verified
                student_answer.status_ta = "v"
            else:  # type_tasks == "p"
                # Для фото – просто помечаем как completed (ожидает проверки репетитора)
                student_answer.status_ta = "c"
                # is_point остаётся None, баллы выставит репетитор позже
        else:
            # Неожиданный статус
            raise HTTPException(500, f"Некорректный статус ответа для задания {task.task_id}")

    db.commit()
    return {"message": "Группа заданий завершена. Текстовые задания проверены автоматически, фото-задания отправлены на проверку."}

@app.delete("/tasks/{task_group_id}")
def delete_task_group(task_group_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_cookies(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только репетитор может удалять группы заданий")
    task_group = db.query(TaskGroup).filter(TaskGroup.id_t_gr == task_group_id).first()
    if not task_group:
        raise HTTPException(404, "Группа заданий не найдена")
    # Проверка прав – принадлежит ли текущему репетитору
    session = task_group.session
    group = session.group
    if group.id_tutor != db.query(Tutor).filter(Tutor.id == user_id).first().id_tutor:
        raise HTTPException(403, "Нет прав на удаление")
    db.delete(task_group)
    db.commit()
    return {"message": "Группа заданий удалена"}

@app.post("/tasks/{task_group_id}/{task_number}/{student_id}")
def tutor_grade_task(
    task_group_id: int,
    task_number: int,
    student_id: int,
    request: Request,
    points: Optional[int] = Form(None),
    comment_text: Optional[str] = Form(None),
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только репетитор может оценивать")

    tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(404, "Репетитор не найден")

    # Находим задание
    tasks = db.query(models.Task).filter(models.Task.id_t_gr == task_group_id).order_by(models.Task.task_id).all()
    if task_number < 1 or task_number > len(tasks):
        raise HTTPException(404, "Задание не найдено")
    task = tasks[task_number - 1]

    # Находим студента
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(404, "Студент не найден")

    # Ищем ответ студента
    student_answer = db.query(models.StudentAnswer).filter(
        models.StudentAnswer.task_id == task.task_id,
        models.StudentAnswer.id_student == student.id_student
    ).first()
    if not student_answer:
        raise HTTPException(404, "Студент ещё не дал ответ на это задание")

    # Обновляем баллы
    if points is not None:
        if points < 0 or points > task.max_point:
            raise HTTPException(400, "Некорректное количество баллов")
        student_answer.is_point = points

    # Сохраняем комментарий
    if comment_text or files:
        # Ищем существующий комментарий
        comment = db.query(models.Comment).filter(models.Comment.answer_id == student_answer.answer_id).first()
        if not comment:
            comment = models.Comment(answer_id=student_answer.answer_id)
            db.add(comment)
            db.flush()
        if comment_text:
            comment.comments = comment_text
        # Файлы комментариев
        for idx, file in enumerate(files):
            ext = Path(file.filename).suffix.lower()
            prefix = f"comment_{comment.id_comments}_{idx}"
            rel_path = save_file(file, COMMENT_PIC_DIR, prefix, ext)
            path_comment = models.PathComment(path_comments=rel_path, id_comments=comment.id_comments)
            db.add(path_comment)
        db.commit()

    return {"message": "Оценка и комментарий сохранены"}

@app.post("/tasks/{task_group_id}/{student_id}/verify")
def verify_task_group(
    task_group_id: int,
    student_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только репетитор может завершить проверку")

    tasks = db.query(models.Task).filter(models.Task.id_t_gr == task_group_id).all()
    for task in tasks:
        student_answer = db.query(models.StudentAnswer).filter(
            models.StudentAnswer.task_id == task.task_id,
            models.StudentAnswer.id_student == student_id
        ).first()
        if student_answer and student_answer.status_ta == "c":
            student_answer.status_ta = "v"   # verified
    db.commit()
    return {"message": "Проверка завершена, результаты видны ученику"}

@app.get("/tasks/create")
def get_tasks_and_sessions_for_creation(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только для репетитора")

    tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(404, "Репетитор не найден")

    # Сессии за 3 месяца
    three_months_ago = datetime.utcnow() - timedelta(days=90)
    sessions = db.query(models.Session).join(
        models.Group, models.Group.id_group == models.Session.id_group
    ).filter(
        models.Group.id_tutor == tutor.id_tutor,
        models.Session.session_date_start >= three_months_ago
    ).order_by(models.Session.session_date_start.desc()).all()

    sessions_info = []
    for sess in sessions:
        group = sess.group
        sessions_info.append({
            "id_session": sess.id_session,
            "name_session": sess.name_session,
            "session_date_start": sess.session_date_start,
            "session_date_end": sess.session_date_end,
            "group_name": group.group_name,
            "group_id": group.id_group
        })

    # Группы заданий (все, без ограничений по дате, можно за 3 месяца)
    task_groups = db.query(models.TaskGroup).join(
        models.Session, models.Session.id_session == models.TaskGroup.id_session
    ).join(
        models.Group, models.Group.id_group == models.Session.id_group
    ).filter(
        models.Group.id_tutor == tutor.id_tutor
    ).order_by(models.Session.session_date_start.desc()).all()

    task_groups_info = []
    for tg in task_groups:
        task_groups_info.append({
            "task_group_id": tg.id_t_gr,
            "task_group_name": tg.name_tgr,
            "session_name": tg.session.name_session,
            "session_date": tg.session.session_date_start
        })

    return {
        "sessions": sessions_info,
        "existing_task_groups": task_groups_info
    }

@app.get("/tasks/create/load/{session_name}")
def load_session_for_create_task(
    session_name: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только для репетитора")

    tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(404, "Репетитор не найден")

    session = db.query(models.Session).join(
        models.Group, models.Group.id_group == models.Session.id_group
    ).filter(
        models.Group.id_tutor == tutor.id_tutor,
        models.Session.name_session == session_name
    ).first()
    if not session:
        raise HTTPException(404, "Сессия не найдена")

    # Возвращаем информацию для заполнения формы создания заданий
    # Можно вернуть данные группы, список учеников и т.д.
    group = session.group
    students = db.query(models.User).join(
        models.Student, models.Student.id == models.User.id
    ).join(
        models.GroupMember, models.GroupMember.id_student == models.Student.id_student
    ).filter(models.GroupMember.id_group == group.id_group).all()

    return {
        "session_id": session.id_session,
        "session_name": session.name_session,
        "session_date": session.session_date_start,
        "group_name": group.group_name,
        "subject": group.subjects,
        "students": [{"id": s.id, "full_name": s.full_name} for s in students]
    }

@app.post("/tasks/create")
async def create_task_group(
    request: Request,
    task_data_json: str = Form(...),
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    # 1. Аутентификация
    user_id = get_user_id_from_cookies(request)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только для репетитора")
    tutor = db.query(models.Tutor).filter(models.Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(404, "Репетитор не найден")

    # 2. Парсим JSON
    try:
        task_group_data = json.loads(task_data_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Неверный JSON")

    # Извлекаем данные
    session_id = task_group_data.get("session_id")
    name_tgr = task_group_data.get("name_tgr")
    deadline_str = task_group_data.get("deadline")
    tasks_data = task_group_data.get("tasks", [])

    if not session_id or not name_tgr or not tasks_data:
        raise HTTPException(400, "Не хватает обязательных полей")

    # Преобразуем deadline в datetime
    try:
        deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
    except:
        raise HTTPException(400, "Неверный формат deadline")

    # Проверяем сессию
    session = db.query(models.Session).join(
        models.Group, models.Group.id_group == models.Session.id_group
    ).filter(
        models.Group.id_tutor == tutor.id_tutor,
        models.Session.id_session == session_id
    ).first()
    if not session:
        raise HTTPException(404, "Сессия не найдена или не принадлежит вам")

    # 3. Создаём TaskGroup
    task_group = models.TaskGroup(
        id_session=session.id_session,
        name_tgr=name_tgr,
        deadline=deadline
    )
    db.add(task_group)
    db.commit()
    db.refresh(task_group)

    file_index = 0
    for task_data in tasks_data:
        description = task_data.get("description")
        type_tasks = task_data.get("type_tasks")
        max_point = task_data.get("max_point")
        correct_answers = task_data.get("correct_answers", [])
        attachments_count = task_data.get("attachments_count", 0)

        if not description or not type_tasks or max_point is None:
            raise HTTPException(400, "Не все поля задания заполнены")

        # Создаём задание
        task = models.Task(
            description=description,
            type_tasks=type_tasks,
            max_point=max_point,
            id_t_gr=task_group.id_t_gr
        )
        db.add(task)
        db.flush()   # чтобы получить task.task_id

        # Сохраняем правильные ответы (для текстовых)
        if type_tasks == "t" and correct_answers:
            for ca in correct_answers:
                correct = models.TaskCorrectAnswer(
                    correct_answer=ca.get("answer"),
                    point=ca.get("point"),
                    task_id=task.task_id
                )
                db.add(correct)

        # Сохраняем файлы (условия) для этого задания
        for _ in range(attachments_count):
            if file_index >= len(files):
                raise HTTPException(400, f"Не хватает файлов для задания {task.task_id}")
            file = files[file_index]
            file_index += 1

            # Сохраняем файл в папку descriptionpic
            ext = Path(file.filename).suffix.lower()
            allowed_ext = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            if ext not in allowed_ext:
                continue
            # Генерируем имя: task_{task_id}_{timestamp}{ext}
            unique_name = f"task_{task.task_id}_{int(datetime.utcnow().timestamp())}{ext}"
            file_path = DESCRIPTION_PIC_DIR / unique_name
            with file_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            # Сохраняем путь в БД
            relative_path = f"descriptionpic/{unique_name}"
            path_desc = models.PathDescription(path=relative_path, task_id=task.task_id)
            db.add(path_desc)

        db.commit()

    return {"message": "Группа заданий создана", "task_group_id": task_group.id_t_gr}

# ==================== РЕПЕТИТОР: ГРУППЫ И ИНДИВИДУАЛЬНЫЕ ====================

@app.get("/my/student/groups", response_model=List[TutorGroupOut])
def get_tutor_groups(request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
    result = []
    for g in groups:
        student_count = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group).count()
        result.append(TutorGroupOut(
            id_group=g.id_group,
            group_name=g.group_name,
            subject=g.subjects,
            student_count=student_count
        ))
    return result

@app.get("/my/student/individual", response_model=List[IndividualStudentOut])
def get_individual_students(request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
    result = []
    for g in groups:
        members = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group).all()
        if len(members) == 1:
            student = members[0].student
            user_student = student.user
            if g.group_name == user_student.full_name:
                result.append(IndividualStudentOut(
                    id_student=student.id_student,
                    full_name=user_student.full_name,
                    photo=user_student.path_profile_pic,
                    subject=g.subjects
                ))
    return result


@app.get("/my/tutor/codes")
def get_all_tutor_codes(request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    subjects = db.query(TutorSubject.subject_name).filter(TutorSubject.id_tutor == tutor.id_tutor).all()

    codes = []
    for subject in subjects:
        code = f"tutor_{tutor.id_tutor}_{subject.subject_name}"
        codes.append({
            "subject": subject.subject_name,
            "code": code
        })

    return {"codes": codes}

@app.get("/my/student/groups/{id_group}", response_model=GroupDetailOut)
def get_group_detail(id_group: int, request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    group = db.query(models.Group).filter(models.Group.id_group == id_group, models.Group.id_tutor == tutor.id_tutor).first()
    if not group:
        raise HTTPException(404, "Группа не найдена")

    members = db.query(models.GroupMember).filter(models.GroupMember.id_group == id_group).all()
    students_in = []
    for m in members:
        student = m.student
        user = student.user
        students_in.append(StudentInGroupOut(
            id_student=student.id_student,
            full_name=user.full_name,
            photo=user.path_profile_pic
        ))

    all_groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
    all_group_ids = [g.id_group for g in all_groups]
    all_members = db.query(models.GroupMember).filter(models.GroupMember.id_group.in_(all_group_ids)).all()
    student_ids_in_current = {m.id_student for m in members}
    student_map = {}
    for m in all_members:
        if m.id_student not in student_ids_in_current:
            if m.id_student not in student_map:
                student = m.student
                user = student.user
                student_map[m.id_student] = StudentInGroupOut(
                    id_student=student.id_student,
                    full_name=user.full_name,
                    photo=user.path_profile_pic
                )
    available = sorted(student_map.values(), key=lambda x: x.full_name)

    return GroupDetailOut(
        group_name=group.group_name,
        subject=group.subjects,
        students=students_in,
        available_students=available
    )

@app.post("/my/student/groups/{id_group}")
def get_formatted_group_id(id_group: int, request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    group = db.query(models.Group).filter(models.Group.id_group == id_group, models.Group.id_tutor == tutor.id_tutor).first()
    if not group:
        raise HTTPException(404, "Группа не найдена")
    return {"formatted_id": f"group_{id_group}"}

@app.post("/my/student/groups", status_code=201)
def create_group(data: CreateGroupRequest, request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    new_group = models.Group(
        group_name=data.group_name,
        subjects=data.subject,
        id_tutor=tutor.id_tutor
    )
    db.add(new_group)
    db.commit()
    db.refresh(new_group)
    return {"id_group": new_group.id_group, "formatted_id": f"group_{new_group.id_group}"}

@app.post("/my/student/groups/{id_student}")
def add_student_to_group(
    id_student: int,
    req: AddStudentToGroupRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    tutor = get_current_tutor(request, db)
    student = db.query(models.Student).filter(models.Student.id_student == id_student).first()
    if not student:
        raise HTTPException(404, "Студент не найден")
    group = db.query(models.Group).filter(models.Group.id_group == req.group_id, models.Group.id_tutor == tutor.id_tutor).first()
    if not group:
        raise HTTPException(404, "Группа не найдена")

    existing = db.query(models.GroupMember).filter(models.GroupMember.id_group == group.id_group, models.GroupMember.id_student == student.id_student).first()
    if existing:
        raise HTTPException(400, "Студент уже в этой группе")

    same_subject_groups = db.query(models.Group).filter(
        models.Group.id_tutor == tutor.id_tutor,
        models.Group.subjects == group.subjects
    ).all()
    for g in same_subject_groups:
        member = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group, models.GroupMember.id_student == student.id_student).first()
        if member:
            db.delete(member)
            remaining = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group).count()
            if remaining == 0 and g.group_name == student.user.full_name:
                db.delete(g)

    new_member = models.GroupMember(id_group=group.id_group, id_student=student.id_student)
    db.add(new_member)
    db.commit()
    return {"message": "Студент добавлен в группу"}

@app.delete("/my/student/groups/{id_group}")
def delete_group(id_group: int, request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    group = db.query(models.Group).filter(models.Group.id_group == id_group, models.Group.id_tutor == tutor.id_tutor).first()
    if not group:
        raise HTTPException(404, "Группа не найдена")
    sessions_count = db.query(models.Session).filter(models.Session.id_group == id_group).count()
    if sessions_count > 0:
        raise HTTPException(400, "Нельзя удалить группу с существующими занятиями")
    db.query(models.GroupMember).filter(models.GroupMember.id_group == id_group).delete()
    db.delete(group)
    db.commit()
    return {"message": "Группа удалена"}

@app.delete("/my/student/individual/{id_student}/{subject}")
def delete_individual_student_by_subject(
    id_student: int,
    subject: SubjectEnum,
    request: Request,
    db: Session = Depends(get_db)
):
    tutor = get_current_tutor(request, db)
    student = db.query(models.Student).filter(models.Student.id_student == id_student).first()
    if not student:
        raise HTTPException(404, "Студент не найден")
    group = db.query(models.Group).filter(
        models.Group.id_tutor == tutor.id_tutor,
        models.Group.subjects == subject.value,
        models.Group.group_name == student.user.full_name
    ).first()
    if not group:
        raise HTTPException(404, "Индивидуальная группа не найдена")
    members = db.query(models.GroupMember).filter(models.GroupMember.id_group == group.id_group).all()
    if len(members) != 1 or members[0].id_student != student.id_student:
        raise HTTPException(400, "Группа не является индивидуальной для этого студента")
    db.query(models.GroupMember).filter(models.GroupMember.id_group == group.id_group).delete()
    db.delete(group)
    db.commit()
    return {"message": "Индивидуальный студент удалён по предмету"}

@app.delete("/my/student/individual/{id_student}")
def delete_individual_student_completely(id_student: int, request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    student = db.query(models.Student).filter(models.Student.id_student == id_student).first()
    if not student:
        raise HTTPException(404, "Студент не найден")
    groups = db.query(models.Group).filter(models.Group.id_tutor == tutor.id_tutor).all()
    for g in groups:
        member = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group, models.GroupMember.id_student == student.id_student).first()
        if member:
            db.delete(member)
            remaining = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group).count()
            if remaining == 0 and g.group_name == student.user.full_name:
                db.delete(g)
    db.commit()
    return {"message": "Студент полностью удалён от репетитора"}

@app.delete("/my/student/groups/{id_group}/{id_student}")
def remove_student_from_group(id_group: int, id_student: int, request: Request, db: Session = Depends(get_db)):
    tutor = get_current_tutor(request, db)
    group = db.query(models.Group).filter(models.Group.id_group == id_group, models.Group.id_tutor == tutor.id_tutor).first()
    if not group:
        raise HTTPException(404, "Группа не найдена")
    student = db.query(models.Student).filter(models.Student.id_student == id_student).first()
    if not student:
        raise HTTPException(404, "Студент не найден")
    member = db.query(models.GroupMember).filter(models.GroupMember.id_group == id_group, models.GroupMember.id_student == student.id_student).first()
    if not member:
        raise HTTPException(404, "Студент не состоит в этой группе")
    db.delete(member)

    individual_group = db.query(models.Group).filter(
        models.Group.id_tutor == tutor.id_tutor,
        models.Group.subjects == group.subjects,
        models.Group.group_name == student.user.full_name
    ).first()
    if not individual_group:
        individual_group = models.Group(
            group_name=student.user.full_name,
            subjects=group.subjects,
            id_tutor=tutor.id_tutor
        )
        db.add(individual_group)
        db.commit()
        db.refresh(individual_group)
    new_member = models.GroupMember(id_group=individual_group.id_group, id_student=student.id_student)
    db.add(new_member)
    db.commit()
    return {"message": "Студент удалён из группы и перенесён в индивидуальные"}

# ==================== СТУДЕНТ: РЕПЕТИТОРЫ ====================

@app.get("/my/tutor", response_model=List[TutorForStudentOut])
def get_my_tutors(request: Request, db: Session = Depends(get_db)):
    student = get_current_student(request, db)
    groups = db.query(models.Group).join(models.GroupMember).filter(models.GroupMember.id_student == student.id_student).all()
    tutor_map = {}
    for g in groups:
        tutor = g.tutor
        user_tutor = tutor.user
        if tutor.id_tutor not in tutor_map:
            tutor_map[tutor.id_tutor] = {
                "id_tutor": tutor.id_tutor,
                "full_name": user_tutor.full_name,
                "subjects": set()
            }
        tutor_map[tutor.id_tutor]["subjects"].add(g.subjects)
    result = []
    for data in tutor_map.values():
        result.append(TutorForStudentOut(
            id_tutor=data["id_tutor"],
            full_name=data["full_name"],
            subjects=list(data["subjects"])
        ))
    return result

@app.post("/student/add", status_code=200)
def student_add_by_code(data: AddStudentByCodeRequest, request: Request, db: Session = Depends(get_db)):
    student = get_current_student(request, db)
    code = data.code
    if code.startswith("tutor_"):
        parts = code.split('_')
        if len(parts) != 3:
            raise HTTPException(400, "Неверный формат кода репетитора")
        try:
            tutor_id = int(parts[1])
        except ValueError:
            raise HTTPException(400, "Неверный id репетитора")
        subject_str = parts[2]
        try:
            subject_enum = SubjectEnum(subject_str)
        except ValueError:
            raise HTTPException(400, "Неверный предмет")
        tutor = db.query(models.Tutor).filter(models.Tutor.id_tutor == tutor_id).first()
        if not tutor:
            raise HTTPException(404, "Репетитор не найден")
        existing = db.query(models.Group).join(models.GroupMember).filter(
            models.Group.id_tutor == tutor_id,
            models.Group.subjects == subject_enum.value,
            models.GroupMember.id_student == student.id_student
        ).first()
        if existing:
            raise HTTPException(400, "Вы уже занимаетесь этим предметом у этого репетитора")
        new_group = models.Group(
            group_name=student.user.full_name,
            subjects=subject_enum.value,
            id_tutor=tutor_id
        )
        db.add(new_group)
        db.commit()
        db.refresh(new_group)
        member = models.GroupMember(id_group=new_group.id_group, id_student=student.id_student)
        db.add(member)
        db.commit()
        return {"message": "Вы добавлены как индивидуальный ученик"}
    elif code.startswith("group_"):
        parts = code.split('_')
        if len(parts) != 2:
            raise HTTPException(400, "Неверный формат кода группы")
        try:
            group_id = int(parts[1])
        except ValueError:
            raise HTTPException(400, "Неверный id группы")
        group = db.query(models.Group).filter(models.Group.id_group == group_id).first()
        if not group:
            raise HTTPException(404, "Группа не найдена")
        existing = db.query(models.GroupMember).filter(models.GroupMember.id_group == group_id, models.GroupMember.id_student == student.id_student).first()
        if existing:
            raise HTTPException(400, "Вы уже в этой группе")
        member = models.GroupMember(id_group=group_id, id_student=student.id_student)
        db.add(member)
        db.commit()
        return {"message": "Вы добавлены в группу"}
    else:
        raise HTTPException(400, "Неизвестный формат кода")

@app.delete("/my/tutor/{id_tutor}")
def remove_tutor_from_student(id_tutor: int, request: Request, db: Session = Depends(get_db)):
    student = get_current_student(request, db)
    groups = db.query(models.Group).join(models.GroupMember).filter(
        models.Group.id_tutor == id_tutor,
        models.GroupMember.id_student == student.id_student
    ).all()
    if not groups:
        raise HTTPException(404, "Репетитор не найден у студента")
    for g in groups:
        db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group, models.GroupMember.id_student == student.id_student).delete()
        remaining = db.query(models.GroupMember).filter(models.GroupMember.id_group == g.id_group).count()
        if remaining == 0 and g.group_name == student.user.full_name:
            db.delete(g)
    db.commit()
    return {"message": "Репетитор удалён"}

# ========== Статистика ==========
@app.get("/statistics")
def get_statistics(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_user_id_from_cookies(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.role == "s":
        student = db.query(Student).filter(Student.id == user_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Студент не найден")

        # Получаем группы студента
        groups = db.query(Group).join(
            GroupMember, GroupMember.id_group == Group.id_group
        ).filter(GroupMember.id_student == student.id_student).all()

        # Уникальные предметы
        subjects = set(g.subjects for g in groups if g.subjects)

        # Если предметов нет – возвращаем пустой массив
        if not subjects:
            return {"subjects": []}

        # Собираем статистику по каждому предмету
        subjects_stats = []
        for subj in subjects:
            stats = compute_student_statistics(student.id_student, db, subject=subj)
            subjects_stats.append({
                "subject": subj,
                "attendance_percent": stats["attendance_percent"],
                "points_earned_percent": stats["points_earned_percent"],
                "homeworks_submitted_percent": stats["homeworks_submitted_percent"],
                "max_score_homeworks_percent": stats["max_score_homeworks_percent"]
            })

        return {"subjects": subjects_stats}

    elif user.role == "t":
        tutor = db.query(Tutor).filter(Tutor.id == user_id).first()
        if not tutor:
            raise HTTPException(status_code=404, detail="Репетитор не найден")

        groups = db.query(Group).filter(Group.id_tutor == tutor.id_tutor).all()
        student_subjects = defaultdict(set)
        for group in groups:
            members = db.query(GroupMember).filter(GroupMember.id_group == group.id_group).all()
            for member in members:
                student_subjects[member.id_student].add(group.subjects)

        result_students = []
        for student_id, subjects in student_subjects.items():
            student_user = db.query(User).join(Student, Student.id == User.id).filter(Student.id_student == student_id).first()
            if not student_user:
                continue
            subjects_stats = []
            for subj in subjects:
                subj_stats = compute_student_statistics(student_id, db, subject=subj)
                subjects_stats.append({
                    "subject": subj,
                    **subj_stats
                })
            result_students.append({
                "student_id": student_id,
                "student_name": student_user.full_name,
                "subjects": subjects_stats
            })
        return {"students": result_students}

    else:
        raise HTTPException(status_code=403, detail="Недопустимая роль")

@app.get("/me/subjects")
def get_my_subjects(request: Request, db: Session = Depends(get_db)):
    """Вернуть список предметов текущего репетитора"""
    tutor = get_current_tutor(request, db)
    subjects = db.query(TutorSubject.subject_name).filter(TutorSubject.id_tutor == tutor.id_tutor).all()
    return {"subjects": [s.subject_name for s in subjects]}