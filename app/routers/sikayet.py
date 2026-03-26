from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Sikayet, SikayetYorum, SikayetDurum, SikayetOncelik,
    Musteri, UretimEmri, UrunParti, HammaddeLot
)

router = APIRouter(prefix="/sikayet", tags=["sikayet"])


def _sikayet_no(db: Session, firma_id: int) -> str:
    sira = db.query(Sikayet).filter(Sikayet.firma_id == firma_id).count() + 1
    return f"SK-{firma_id:02d}-{datetime.now().strftime('%y')}-{sira:04d}"


@router.get("/", response_class=HTMLResponse)
def sikayet_listesi(
    request: Request,
    durum: Optional[str] = Query(None),
    oncelik: Optional[str] = Query(None),
    recall: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    q = db.query(Sikayet).filter(Sikayet.firma_id == fid)
    if durum:   q = q.filter(Sikayet.durum == durum)
    if oncelik: q = q.filter(Sikayet.oncelik == oncelik)
    if recall == "1": q = q.filter(Sikayet.is_recall == True)
    sikayetler = q.order_by(Sikayet.created_at.desc()).all()

    musteriler = db.query(Musteri).filter(Musteri.firma_id == fid, Musteri.aktif == True).all()
    partiler   = db.query(UrunParti).filter(UrunParti.firma_id == fid).order_by(UrunParti.created_at.desc()).limit(50).all()
    emirler    = db.query(UretimEmri).filter(UretimEmri.firma_id == fid).order_by(UretimEmri.created_at.desc()).limit(50).all()

    # KPI
    aktif_recall = db.query(Sikayet).filter(
        Sikayet.firma_id == fid,
        Sikayet.is_recall == True,
        Sikayet.durum == SikayetDurum.recall
    ).count()
    kritik_acik = db.query(Sikayet).filter(
        Sikayet.firma_id == fid,
        Sikayet.oncelik == SikayetOncelik.kritik,
        Sikayet.durum != SikayetDurum.kapatildi
    ).count()

    return templates.TemplateResponse("sikayet/liste.html", {
        "request": request, "user": user,
        "sikayetler": sikayetler,
        "musteriler": musteriler,
        "partiler": partiler,
        "emirler": emirler,
        "aktif_recall": aktif_recall,
        "kritik_acik": kritik_acik,
        "SikayetDurum": SikayetDurum,
        "SikayetOncelik": SikayetOncelik,
        "filtre_durum": durum,
        "filtre_oncelik": oncelik,
        "filtre_recall": recall,
    })


@router.post("/ekle")
def sikayet_ekle(
    baslik: str = Form(...),
    aciklama: str = Form(...),
    oncelik: str = Form("orta"),
    musteri_id: str = Form(""),
    uretim_emri_id: str = Form(""),
    urun_parti_id: str = Form(""),
    is_recall: Optional[str] = Form(None),
    etkilenen_miktar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid  = user.firma_id
    no   = _sikayet_no(db, fid)
    recall_flag = is_recall == "on"

    s = Sikayet(
        firma_id         = fid,
        sikayet_no       = no,
        baslik           = baslik,
        aciklama         = aciklama,
        oncelik          = oncelik,
        musteri_id       = safe_int(musteri_id),
        uretim_emri_id   = safe_int(uretim_emri_id),
        urun_parti_id    = safe_int(urun_parti_id),
        is_recall        = recall_flag,
        etkilenen_miktar = safe_float(etkilenen_miktar),
        durum            = SikayetDurum.recall if recall_flag else SikayetDurum.acik,
        created_by       = user.id,
    )
    db.add(s); db.commit(); db.refresh(s)
    return RedirectResponse(f"/sikayet/{s.id}", status_code=302)


@router.get("/{sid}", response_class=HTMLResponse)
def sikayet_detay(
    sid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    s = db.query(Sikayet).filter(Sikayet.id == sid, Sikayet.firma_id == user.firma_id).first()
    if not s: return RedirectResponse("/sikayet/", status_code=302)

    # Geriye iz — parti → üretim → lotlar
    iz_lotlar = []
    if s.urun_parti and s.urun_parti.uretim_emri:
        from app.models.models import UretimHammadde
        iz_lotlar = db.query(UretimHammadde).filter(
            UretimHammadde.emir_id == s.urun_parti.uretim_emri_id
        ).all()

    return templates.TemplateResponse("sikayet/detay.html", {
        "request": request, "user": user,
        "sikayet": s,
        "iz_lotlar": iz_lotlar,
        "SikayetDurum": SikayetDurum,
        "SikayetOncelik": SikayetOncelik,
    })


@router.post("/{sid}/yorum")
def yorum_ekle(
    sid: int, metin: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(SikayetYorum(sikayet_id=sid, kullanici_id=user.id, metin=metin))
    db.commit()
    return RedirectResponse(f"/sikayet/{sid}", status_code=302)


@router.post("/{sid}/guncelle")
def sikayet_guncelle(
    sid: int,
    durum: str = Form(...),
    kok_neden: str = Form(""),
    duzeltici_eylem: str = Form(""),
    geri_cagrilan: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    s = db.query(Sikayet).filter(Sikayet.id == sid, Sikayet.firma_id == user.firma_id).first()
    if s:
        s.durum = durum
        if kok_neden:       s.kok_neden = kok_neden
        if duzeltici_eylem: s.duzeltici_eylem = duzeltici_eylem
        if geri_cagrilan is not None: s.geri_cagrilan = geri_cagrilan
        if durum == SikayetDurum.kapatildi:
            s.kapanis_tarihi = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(f"/sikayet/{sid}", status_code=302)
