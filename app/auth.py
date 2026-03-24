import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Kullanici, KullaniciYetki, Modul

SECRET_KEY = os.environ.get("SECRET_KEY", "traceway-gizli-anahtar-2024-degistir")
ALGORITHM  = "HS256"
TOKEN_HOURS = 10

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[Kullanici]:
    """Cookie'den kullanıcıyı döner. Yoksa None."""
    token = request.cookies.get("tw_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = db.query(Kullanici).filter(
        Kullanici.id == payload.get("sub"),
        Kullanici.aktif == True
    ).first()
    return user


def get_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[Kullanici]:
    return get_current_user(request, db)


def kullanici_yetki(user: Kullanici, modul: Modul, giris: bool = False) -> bool:
    if not user:
        return False
    if user.is_super or user.is_firma_admin:
        return True
    yetki = next((y for y in user.yetkiler if y.modul == modul), None)
    if not yetki:
        return False
    return yetki.giris_yapabilir if giris else yetki.gorebilir


def yetki_kontrol(modul: Modul, giris: bool = False):
    def _check(user: Kullanici = Depends(get_current_user)):
        if not user or not kullanici_yetki(user, modul, giris):
            raise HTTPException(status_code=403, detail="Yetkiniz yok.")
        return user
    return _check


def tum_yetkiler_olustur(db: Session, kullanici_id: int, firma_admin: bool = False):
    moduller = list(Modul)
    for m in moduller:
        mevcut = db.query(KullaniciYetki).filter(
            KullaniciYetki.kullanici_id == kullanici_id,
            KullaniciYetki.modul == m
        ).first()
        if not mevcut:
            db.add(KullaniciYetki(
                kullanici_id    = kullanici_id,
                modul           = m,
                gorebilir       = firma_admin,
                giris_yapabilir = firma_admin,
            ))
