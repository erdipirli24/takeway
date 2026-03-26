from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates, safe_float, safe_int
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Makine, MacineDurum, MakineBakimKaydi, UretimEmri, UretimMakineAtama
)

router = APIRouter(prefix="/makine", tags=["makine"])


@router.get("/", response_class=HTMLResponse)
def makine_listesi(
    request: Request,
    durum: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(Makine).filter(Makine.firma_id == user.firma_id)
    if durum:
        q = q.filter(Makine.durum == durum)
    makineler = q.order_by(Makine.tip, Makine.ad).all()

    # Her makine için aktif üretim sayısı
    aktif_uretim = {}
    for m in makineler:
        aktif_uretim[m.id] = db.query(UretimMakineAtama).join(UretimEmri).filter(
            UretimMakineAtama.makine_id == m.id,
            UretimEmri.durum == "devam"
        ).count()

    return templates.TemplateResponse("makine/liste.html", {
        "request": request, "user": user,
        "makineler": makineler,
        "aktif_uretim": aktif_uretim,
        "MacineDurum": MacineDurum,
        "filtre_durum": durum,
    })


@router.post("/ekle")
def makine_ekle(
    ad: str = Form(...),
    kod: str = Form(""),
    tip: str = Form(""),
    marka: str = Form(""),
    model: str = Form(""),
    seri_no: str = Form(""),
    kapasite: str = Form(""),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    m = Makine(
        firma_id = user.firma_id,
        ad       = ad, kod=kod or None, tip=tip or None,
        marka=marka or None, model=model or None,
        seri_no=seri_no or None, kapasite=kapasite or None,
        notlar=notlar or None,
        durum    = MacineDurum.aktif,
    )
    db.add(m); db.commit()
    return RedirectResponse("/makine/", status_code=302)


@router.get("/{mid}", response_class=HTMLResponse)
def makine_detay(
    mid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    makine = db.query(Makine).filter(Makine.id == mid, Makine.firma_id == user.firma_id).first()
    if not makine:
        return RedirectResponse("/makine/", status_code=302)

    bakim_kayitlari = db.query(MakineBakimKaydi).filter(
        MakineBakimKaydi.makine_id == mid
    ).order_by(MakineBakimKaydi.tarih.desc()).limit(20).all()

    aktif_uretimler = db.query(UretimEmri).join(UretimMakineAtama).filter(
        UretimMakineAtama.makine_id == mid,
        UretimEmri.durum == "devam"
    ).all()

    return templates.TemplateResponse("makine/detay.html", {
        "request": request, "user": user,
        "makine": makine,
        "bakim_kayitlari": bakim_kayitlari,
        "aktif_uretimler": aktif_uretimler,
        "MacineDurum": MacineDurum,
    })


@router.post("/{mid}/durum")
def makine_durum(
    mid: int,
    durum: str = Form(...),
    bakim_notu: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    m = db.query(Makine).filter(Makine.id == mid, Makine.firma_id == user.firma_id).first()
    if m:
        m.durum = durum
        if bakim_notu:
            m.bakim_notu = bakim_notu
        db.commit()
    return RedirectResponse(f"/makine/{mid}", status_code=302)


@router.post("/{mid}/bakim-ekle")
def bakim_ekle(
    mid: int,
    tip: str = Form("Periyodik"),
    aciklama: str = Form(""),
    yapan: str = Form(""),
    maliyet: str = Form(""),
    sonraki_bakim: Optional[str] = Form(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    def parse_dt(s):
        if s:
            try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except: pass
        return None

    m = db.query(Makine).filter(Makine.id == mid, Makine.firma_id == user.firma_id).first()
    if m:
        db.add(MakineBakimKaydi(
            makine_id  = mid,
            tip        = tip,
            aciklama   = aciklama or None,
            yapan      = yapan or None,
            maliyet    = safe_float(maliyet),
            created_by = user.id,
        ))
        m.son_bakim     = datetime.now(timezone.utc)
        m.sonraki_bakim = parse_dt(sonraki_bakim)
        if tip == "Arıza":
            m.durum = MacineDurum.arizali
        elif tip == "Bakım":
            m.durum = MacineDurum.bakim
        db.commit()
    return RedirectResponse(f"/makine/{mid}", status_code=302)
