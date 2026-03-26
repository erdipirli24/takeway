from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os

from app.database import get_db
from app.models.models import Kullanici
from app.auth import verify_password, create_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# Railway HTTPS'de çalışıyor — secure=True zorunlu
IS_PRODUCTION = os.environ.get("DATABASE_URL", "").startswith("postgresql")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {
        "request": request, "error": None
    })


@router.post("/login")
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        # Email büyük/küçük harf duyarsız ara
        user = db.query(Kullanici).filter(
            Kullanici.aktif == True
        ).all()
        user = next(
            (u for u in user if u.email.lower() == email.strip().lower()),
            None
        )

        if not user or not verify_password(password, user.hashed_pw):
            return templates.TemplateResponse("auth/login.html", {
                "request": request,
                "error": "E-posta veya şifre hatalı."
            })

        user.last_login = datetime.now(timezone.utc)
        db.commit()

        token = create_token({"sub": user.id, "firma_id": user.firma_id})

        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie(
            key="tw_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=36000,
            secure=IS_PRODUCTION,  # HTTPS'de True
            path="/",
        )
        return resp

    except Exception as e:
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": f"Hata: {str(e)}"
        })


@router.get("/logout")
def logout():
    resp = RedirectResponse("/auth/login", status_code=302)
    resp.delete_cookie("tw_token", path="/")
    return resp
