import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Kullanici, KullaniciYetki, Modul

SECRET_KEY  = os.environ.get("SECRET_KEY", "traceway-gizli-anahtar-2024-degistir")
ALGORITHM   = "HS256"
TOKEN_HOURS = 24

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    # sub mutlaka string olsun
    payload["sub"] = str(payload.get("sub", ""))
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[Kullanici]:
    """Cookie'den kullanıcıyı döner. Geçersizse None."""
    token = request.cookies.get("tw_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        user = db.query(Kullanici).filter(
            Kullanici.id == user_id,
            Kullanici.aktif == True
        ).first()
        return user
    except Exception:
        return None


def kullanici_yetki(user: Optional[Kullanici], modul: Modul, giris: bool = False) -> bool:
    if not user:
        return False
    if user.is_super or user.is_firma_admin:
        return True
    yetki = next((y for y in user.yetkiler if y.modul == modul), None)
    if not yetki:
        return False
    return yetki.giris_yapabilir if giris else yetki.gorebilir


def tum_yetkiler_olustur(db: Session, kullanici_id: int, firma_admin: bool = False):
    for m in list(Modul):
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
