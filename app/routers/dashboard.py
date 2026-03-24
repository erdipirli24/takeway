from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
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
    """Kullanıcının görebileceği firma ID'leri (merkez + şubeler)."""
    if user.is_super:
        return [f.id for f in db.query(Firma.id).all()]
    firma = db.query(Firma).filter(Firma.id == user.firma_id).first()
    if not firma:
        return []
    ids = [firma.id]
    if firma.tip.value == "merkez":
        ids += [s.id for s in firma.subeler]
    return ids


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid_list = firma_id_listesi(user, db)
    now = datetime.now(timezone.utc)
    limit_30 = now + timedelta(days=30)

    aktif_lot = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id.in_(fid_list),
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda])
    ).count()

    karantina = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id.in_(fid_list),
        HammaddeLot.durum == LotDurum.karantina
    ).count()

    bekleyen_numune = db.query(Numune).filter(
        Numune.firma_id.in_(fid_list),
        Numune.durum == NumuneDurum.beklemede
    ).count()

    skt_yaklasan = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id.in_(fid_list),
        HammaddeLot.son_kullanma <= limit_30,
        HammaddeLot.son_kullanma >= now,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda, LotDurum.beklemede])
    ).order_by(HammaddeLot.son_kullanma.asc()).limit(10).all()

    son_lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id.in_(fid_list)
    ).order_by(HammaddeLot.created_at.desc()).limit(8).all()

    son_numuneler = db.query(Numune).filter(
        Numune.firma_id.in_(fid_list)
    ).order_by(Numune.created_at.desc()).limit(6).all()

    # Şube listesi (merkez için)
    subeler = []
    if user.firma_id:
        firma = db.query(Firma).filter(Firma.id == user.firma_id).first()
        if firma and firma.tip.value == "merkez":
            subeler = firma.subeler

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "user": user,
        "now": now,
        "aktif_lot": aktif_lot,
        "karantina": karantina,
        "bekleyen_numune": bekleyen_numune,
        "skt_yaklasan": skt_yaklasan,
        "son_lotlar": son_lotlar,
        "son_numuneler": son_numuneler,
        "subeler": subeler,
    })
