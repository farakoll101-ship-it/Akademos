from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String)

    administrator = relationship("Administrator", back_populates="user", uselist=False)
    tutor = relationship("Tutor", back_populates="user", uselist=False)
    student = relationship("Student", back_populates="user", uselist=False)
    path_profile_pic = Column(String, nullable=True)
class Administrator(Base):
    __tablename__ = 'administrators'
    id_adm = Column(Integer, primary_key=True)
    rights = Column(String, nullable=False)
    id = Column(Integer, ForeignKey('users.id'), unique=True)

    user = relationship("User", back_populates="administrator")
    tutors = relationship("Tutor", back_populates="administrator")

class Tutor(Base):
    __tablename__ = 'tutors'
    id_tutor = Column(Integer, primary_key=True)
    id = Column(Integer, ForeignKey('users.id'), unique=True)
    id_adm = Column(Integer, ForeignKey('administrators.id_adm'))

    user = relationship("User", back_populates="tutor")
    administrator = relationship("Administrator", back_populates="tutors")
    tutor_subjects = relationship("TutorSubject", back_populates="tutor")
    groups = relationship("Group", back_populates="tutor")

class TutorSubject(Base):
    __tablename__ = 'tutor_subjects'
    id_tutor_subject = Column(Integer, primary_key=True)
    subject_name = Column(String)
    id_tutor = Column(Integer, ForeignKey('tutors.id_tutor'))

    tutor = relationship("Tutor", back_populates="tutor_subjects")

class Student(Base):
    __tablename__ = 'students'
    id_student = Column(Integer, primary_key=True)
    id = Column(Integer, ForeignKey('users.id'), unique=True)

    user = relationship("User", back_populates="student")
    group_memberships = relationship("GroupMember", back_populates="student")
    answers = relationship("StudentAnswer", back_populates="student")

class Group(Base):
    __tablename__ = 'groups'
    id_group = Column(Integer, primary_key=True)
    group_name = Column(String)
    subjects = Column(String)
    id_tutor = Column(Integer, ForeignKey('tutors.id_tutor'))

    tutor = relationship("Tutor", back_populates="groups")
    members = relationship("GroupMember", back_populates="group")
    sessions = relationship("Session", back_populates="group")

class GroupMember(Base):
    __tablename__ = 'group_members'
    id_gr_m = Column(Integer, primary_key=True)
    id_group = Column(Integer, ForeignKey('groups.id_group'))
    id_student = Column(Integer, ForeignKey('students.id_student'))

    group = relationship("Group", back_populates="members")
    student = relationship("Student", back_populates="group_memberships")

class Session(Base):
    __tablename__ = 'sessions'
    id_session = Column(Integer, primary_key=True)
    name_session = Column(String)
    id_group = Column(Integer, ForeignKey('groups.id_group'))
    session_date_start = Column(DateTime)
    session_date_end = Column(DateTime)
    status = Column(String, default='p')

    group = relationship("Group", back_populates="sessions")
    task_groups = relationship("TaskGroup", back_populates="session")

class TaskGroup(Base):
    __tablename__ = 'task_group'
    id_t_gr = Column(Integer, primary_key=True)
    id_session = Column(Integer, ForeignKey('sessions.id_session'))
    name_tgr = Column(String)
    deadline = Column(DateTime)
    session = relationship("Session", back_populates="task_groups")
    tasks = relationship("Task", back_populates="task_group")

class Task(Base):
    __tablename__ = 'tasks'
    task_id = Column(Integer, primary_key=True)
    description = Column(Text)
    type_tasks = Column(String)
    max_point = Column(Integer)
    id_t_gr = Column(Integer, ForeignKey('task_group.id_t_gr'))

    task_group = relationship("TaskGroup", back_populates="tasks")
    path_descriptions = relationship("PathDescription", back_populates="task")
    student_answers = relationship("StudentAnswer", back_populates="task")
    correct_answers = relationship("TaskCorrectAnswer", back_populates="task")

class TaskCorrectAnswer(Base):
    __tablename__ = 'task_correct_answer'
    correct_answer_id = Column(Integer, primary_key=True)
    correct_answer = Column(String(1000))
    point = Column(Integer)
    task_id = Column(Integer, ForeignKey('tasks.task_id'))

    task = relationship("Task", back_populates="correct_answers")

class PathDescription(Base):
    __tablename__ = 'path_description'
    id_path_description = Column(Integer, primary_key=True)
    path = Column(Text)
    task_id = Column(Integer, ForeignKey('tasks.task_id'))

    task = relationship("Task", back_populates="path_descriptions")

class StudentAnswer(Base):
    __tablename__ = 'student_answers'
    answer_id = Column(Integer, primary_key=True)
    answer = Column(Text)
    task_id = Column(Integer, ForeignKey('tasks.task_id'))
    is_point = Column(Integer)
    status_ta = Column(String, default='u')
    id_student = Column(Integer, ForeignKey('students.id_student'))

    task = relationship("Task", back_populates="student_answers")
    student = relationship("Student", back_populates="answers")
    comments = relationship("Comment", back_populates="answer")
    path_answers = relationship("PathAnswer", back_populates="answer")

class Comment(Base):
    __tablename__ = 'comments'
    id_comments = Column(Integer, primary_key=True)
    comments = Column(Text)
    answer_id = Column(Integer, ForeignKey('student_answers.answer_id'))

    answer = relationship("StudentAnswer", back_populates="comments")
    path_comments = relationship("PathComment", back_populates="comment")

class PathComment(Base):
    __tablename__ = 'path_comments'
    id_path_comments = Column(Integer, primary_key=True)
    path_comments = Column(Text)
    id_comments = Column(Integer, ForeignKey('comments.id_comments'))

    comment = relationship("Comment", back_populates="path_comments")

class PathAnswer(Base):
    __tablename__ = 'path_answer'
    id_path_answer = Column(Integer, primary_key=True)
    path = Column(Text)
    answer_id = Column(Integer, ForeignKey('student_answers.answer_id'))

    answer = relationship("StudentAnswer", back_populates="path_answers")
