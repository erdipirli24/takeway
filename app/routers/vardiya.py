from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Vardiya, VardiyaPersonel, VardiyaUretim,
    VardiyaTip, UretimEmri, UretimDurum
)

router = APIRouter(prefix="/vardiya", tags=["vardiya"])


def _parse_dt(s):
    if s:
        try: return datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        except:
            try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except: pass
    return None


@router.get("/", response_class=HTMLResponse)
def vardiya_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    vardiyalar = db.query(Vardiya).filter(
        Vardiya.firma_id == fid
    ).order_by(Vardiya.tarih.desc()).limit(30).all()

    kullanicilar = db.query(Kullanici).filter(
        Kullanici.firma_id == fid, Kullanici.aktif == True
    ).all()

    aktif_emirler = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.durum.in_([UretimDurum.planlandı, UretimDurum.devam])
    ).all()

    return templates.TemplateResponse("vardiya/liste.html", {
        "request": request, "user": user,
        "vardiyalar": vardiyalar,
        "kullanicilar": kullanicilar,
        "aktif_emirler": aktif_emirler,
        "VardiyaTip": VardiyaTip,
    })


@router.post("/ekle")
def vardiya_ekle(
    tarih: str = Form(...),
    tip: str = Form("sabah"),
    sorumlu_id: Optional[int] = Form(None),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    v = Vardiya(
        firma_id   = user.firma_id,
        tarih      = _parse_dt(tarih) or datetime.now(timezone.utc),
        tip        = tip,
        sorumlu_id = sorumlu_id or None,
        baslangic  = _parse_dt(tarih),
        notlar     = notlar or None,
    )
    db.add(v); db.commit(); db.refresh(v)
    return RedirectResponse(f"/vardiya/{v.id}", status_code=302)


@router.get("/{vid}", response_class=HTMLResponse)
def vardiya_detay(
    vid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    v = db.query(Vardiya).filter(Vardiya.id == vid, Vardiya.firma_id == user.firma_id).first()
    if not v: return RedirectResponse("/vardiya/", status_code=302)

    kullanicilar = db.query(Kullanici).filter(
        Kullanici.firma_id == user.firma_id, Kullanici.aktif == True
    ).all()
    aktif_emirler = db.query(UretimEmri).filter(
        UretimEmri.firma_id == user.firma_id,
        UretimEmri.durum.in_([UretimDurum.planlandı, UretimDurum.devam])
    ).all()

    return templates.TemplateResponse("vardiya/detay.html", {
        "request": request, "user": user,
        "vardiya": v,
        "kullanicilar": kullanicilar,
        "aktif_emirler": aktif_emirler,
        "VardiyaTip": VardiyaTip,
    })


@router.post("/{vid}/personel-ekle")
def personel_ekle(
    vid: int,
    kullanici_id: int = Form(...),
    gorev: str = Form(""),
    giris: Optional[str] = Form(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(VardiyaPersonel(
        vardiya_id=vid, kullanici_id=kullanici_id,
        gorev=gorev or None, giris=_parse_dt(giris)
    ))
    db.commit()
    return RedirectResponse(f"/vardiya/{vid}", status_code=302)


@router.post("/{vid}/uretim-ekle")
def uretim_ekle(
    vid: int,
    uretim_emri_id: int = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    mevcut = db.query(VardiyaUretim).filter(
        VardiyaUretim.vardiya_id == vid,
        VardiyaUretim.uretim_emri_id == uretim_emri_id
    ).first()
    if not mevcut:
        db.add(VardiyaUretim(vardiya_id=vid, uretim_emri_id=uretim_emri_id))
        db.commit()
    return RedirectResponse(f"/vardiya/{vid}", status_code=302)


@router.post("/{vid}/kapat")
def vardiya_kapat(
    vid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    v = db.query(Vardiya).filter(Vardiya.id == vid, Vardiya.firma_id == user.firma_id).first()
    if v:
        v.bitis = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(f"/vardiya/{vid}", status_code=302)
