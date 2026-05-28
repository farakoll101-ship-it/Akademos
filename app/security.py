from fastapi import Request, Response, Depends, HTTPException, status
from jose import jwt, JWTError
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import User, Tutor, Student

SECRET_KEY = "супер-секретный-ключ"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Токен недействителен или истёк")

def set_token_cookies(response: Response, access: str, refresh: str):
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    )

def unset_token_cookies(response: Response):
    response.delete_cookie(ACCESS_COOKIE_NAME)
    response.delete_cookie(REFRESH_COOKIE_NAME)

def get_access_token_payload(request: Request) -> dict:
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Access-токен не найден в куках")
    return decode_token(token)

def get_refresh_token_payload(request: Request) -> dict:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Refresh-токен не найден в куках")
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Токен не является refresh-токеном")
    return payload

# def get_user_id_from_cookies(request: Request) -> int:
#     # ТЕСТОВЫЙ ОБХОД: если есть заголовок X-User-Id, используем его
#     test_user_id = request.headers.get("X-User-Id")
#     if test_user_id:
#         return int(test_user_id)
#
#     # Обычная логика с куками
#     token = request.cookies.get(ACCESS_COOKIE_NAME)
#     if not token:
#         raise HTTPException(status_code=401, detail="Access-токен не найден в куках")
#     payload = decode_token(token)
#     user_id = payload.get("sub")
#     if not user_id:
#         raise HTTPException(401, detail="Неверный формат токена (отсутствует subject)")
#     return int(user_id)

def get_user_id_from_cookies(request: Request) -> int:
    payload = get_access_token_payload(request)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат токена (отсутствует subject)"
        )
    return int(user_id)

def get_current_tutor(request: Request, db: Session):
    user_id = get_user_id_from_cookies(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.role != "t":
        raise HTTPException(403, "Только для репетитора")
    tutor = db.query(Tutor).filter(Tutor.id == user_id).first()
    if not tutor:
        raise HTTPException(404, "Репетитор не найден")
    return tutor

def get_current_student(request: Request, db: Session):
    user_id = get_user_id_from_cookies(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.role != "s":
        raise HTTPException(403, "Только для студента")
    student = db.query(Student).filter(Student.id == user_id).first()
    if not student:
        raise HTTPException(404, "Студент не найден")
    return student