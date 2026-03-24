"""
Etiket Yönetimi
Lot, ürün partisi, numune ve sevkiyat etiketleri.
Yazdır butonuna basılınca tarayıcı print dialog'u açar.
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, HammaddeLot, UrunParti, Numune,
    Sevkiyat, EtiketSablon
)

router = APIRouter(prefix="/etiket", tags=["etiket"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def etiket_anasayfa(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sablonlar = db.query(EtiketSablon).filter(
        EtiketSablon.firma_id == user.firma_id,
        EtiketSablon.aktif == True
    ).all()
    return templates.TemplateResponse("etiket/anasayfa.html", {
        "request": request, "user": user, "sablonlar": sablonlar
    })


@router.get("/lot/{lid}", response_class=HTMLResponse)
def lot_etiketi(
    lid: int, request: Request,
    adet: int = Query(1),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    lot = db.query(HammaddeLot).filter(
        HammaddeLot.id == lid, HammaddeLot.firma_id == user.firma_id
    ).first()
    if not lot: return RedirectResponse("/depo/stok", status_code=302)
    return templates.TemplateResponse("etiket/lot_etiketi.html", {
        "request": request, "user": user,
        "lot": lot, "adet": adet,
        "now": datetime.now(timezone.utc),
    })


@router.get("/parti/{pid}", response_class=HTMLResponse)
def parti_etiketi(
    pid: int, request: Request,
    adet: int = Query(1),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    parti = db.query(UrunParti).filter(
        UrunParti.id == pid, UrunParti.firma_id == user.firma_id
    ).first()
    if not parti: return RedirectResponse("/uretim/", status_code=302)

    # Allerjenler — reçeteden otomatik
    alerjenler = set()
    if parti.uretim_emri and parti.uretim_emri.recete:
        for k in parti.uretim_emri.recete.kalemler:
            if k.hammadde and k.hammadde.alerjenler:
                alerjenler.update(k.hammadde.alerjen_listesi)

    return templates.TemplateResponse("etiket/parti_etiketi.html", {
        "request": request, "user": user,
        "parti": parti, "adet": adet,
        "alerjenler": sorted(alerjenler),
        "firma": db.query(__import__('app.models.models', fromlist=['Firma']).Firma).filter_by(id=user.firma_id).first(),
        "now": datetime.now(timezone.utc),
    })


@router.get("/numune/{nid}", response_class=HTMLResponse)
def numune_etiketi(
    nid: int, request: Request,
    adet: int = Query(1),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    numune = db.query(Numune).filter(
        Numune.id == nid, Numune.firma_id == user.firma_id
    ).first()
    if not numune: return RedirectResponse("/depo/numune", status_code=302)
    return templates.TemplateResponse("etiket/numune_etiketi.html", {
        "request": request, "user": user,
        "numune": numune, "adet": adet,
        "now": datetime.now(timezone.utc),
    })


@router.get("/sevkiyat/{svid}", response_class=HTMLResponse)
def sevkiyat_etiketi(
    svid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sv = db.query(Sevkiyat).filter(
        Sevkiyat.id == svid, Sevkiyat.firma_id == user.firma_id
    ).first()
    if not sv: return RedirectResponse("/satis/sevkiyat", status_code=302)
    firma = db.query(__import__('app.models.models', fromlist=['Firma']).Firma).filter_by(id=user.firma_id).first()
    return templates.TemplateResponse("etiket/sevkiyat_etiketi.html", {
        "request": request, "user": user,
        "sv": sv, "firma": firma,
        "now": datetime.now(timezone.utc),
    })


@router.post("/sablon/ekle")
def sablon_ekle(
    ad: str = Form(...),
    tip: str = Form(...),
    genislik_mm: int = Form(100),
    yukseklik_mm: int = Form(60),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(EtiketSablon(
        firma_id=user.firma_id, ad=ad, tip=tip,
        genislik_mm=genislik_mm, yukseklik_mm=yukseklik_mm
    ))
    db.commit()
    return RedirectResponse("/etiket/", status_code=302)
