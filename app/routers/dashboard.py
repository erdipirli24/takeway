from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Firma, HammaddeLot, Numune,
    LotDurum, NumuneDurum
)

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def firma_id_listesi(user: Kullanici, db: Session):
    if user.is_super:
        return [row[0] for row in db.query(Firma.id).all()]
    if not user.firma_id:
        return []
    firma = db.query(Firma).filter(Firma.id == user.firma_id).first()
    if not firma:
        return []
    ids = [firma.id]
    try:
        if firma.tip.value == "merkez":
            ids += [s.id for s in firma.subeler]
    except Exception:
        pass
    return ids


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Cookie debug
    token = request.cookies.get("tw_token")
    if not user:
        print(f"[DASHBOARD] user=None, cookie={'mevcut' if token else 'YOK'}")
        if token:
            from app.auth import decode_token
            payload = decode_token(token)
            print(f"[DASHBOARD] token payload: {payload}")
        return RedirectResponse("/auth/login", status_code=302)

    print(f"[DASHBOARD] user={user.email}, firma_id={user.firma_id}")

    fid_list = firma_id_listesi(user, db)
    now      = datetime.now(timezone.utc)
    limit_30 = now + timedelta(days=30)

    try:
        aktif_lot = db.query(HammaddeLot).filter(
            HammaddeLot.firma_id.in_(fid_list),
            HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda])
        ).count() if fid_list else 0

        karantina = db.query(HammaddeLot).filter(
            HammaddeLot.firma_id.in_(fid_list),
            HammaddeLot.durum == LotDurum.karantina
        ).count() if fid_list else 0

        bekleyen_numune = db.query(Numune).filter(
            Numune.firma_id.in_(fid_list),
            Numune.durum == NumuneDurum.beklemede
        ).count() if fid_list else 0

        skt_yaklasan = db.query(HammaddeLot).filter(
            HammaddeLot.firma_id.in_(fid_list),
            HammaddeLot.son_kullanma <= limit_30,
            HammaddeLot.son_kullanma >= now,
            HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda, LotDurum.beklemede])
        ).order_by(HammaddeLot.son_kullanma.asc()).limit(10).all() if fid_list else []

        son_lotlar = db.query(HammaddeLot).filter(
            HammaddeLot.firma_id.in_(fid_list)
        ).order_by(HammaddeLot.created_at.desc()).limit(8).all() if fid_list else []

    except Exception as e:
        print(f"[DASHBOARD] DB sorgu hatası: {e}")
        aktif_lot = karantina = bekleyen_numune = 0
        skt_yaklasan = son_lotlar = []

    subeler = []
    try:
        if user.firma_id:
            firma = db.query(Firma).filter(Firma.id == user.firma_id).first()
            if firma and firma.tip.value == "merkez":
                subeler = firma.subeler
    except Exception:
        pass

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "user": user,
        "now": now,
        "aktif_lot": aktif_lot,
        "karantina": karantina,
        "bekleyen_numune": bekleyen_numune,
        "skt_yaklasan": skt_yaklasan,
        "son_lotlar": son_lotlar,
        "subeler": subeler,
    })
