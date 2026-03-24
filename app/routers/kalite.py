from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, CCPTanim, CCPOlcum, CCPKategori, CCPDurum,
    TemizlikPlan, TemizlikKayit, TemizlikDurum,
    UretimEmri, UretimAsama
)

router = APIRouter(prefix="/kalite", tags=["kalite"])
templates = Jinja2Templates(directory="app/templates")


# ═══ CCP TANIMLAR ════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
def kalite_anasayfa(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    ccp_tanimlar = db.query(CCPTanim).filter(CCPTanim.firma_id == fid, CCPTanim.aktif == True).all()

    # Son 30 ölçüm
    son_olcumler = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == fid
    ).order_by(CCPOlcum.olcum_tarihi.desc()).limit(20).all()

    sapma_sayisi = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == fid,
        CCPOlcum.durum.in_([CCPDurum.sapma, CCPDurum.kritik])
    ).count()

    # Bugünkü temizlikler
    bugun = datetime.now(timezone.utc).date()
    bugun_temizlik = db.query(TemizlikKayit).filter(
        TemizlikKayit.firma_id == fid,
        TemizlikKayit.created_at >= datetime.combine(bugun, datetime.min.time()).replace(tzinfo=timezone.utc)
    ).count()

    return templates.TemplateResponse("kalite/anasayfa.html", {
        "request": request, "user": user,
        "ccp_tanimlar": ccp_tanimlar,
        "son_olcumler": son_olcumler,
        "sapma_sayisi": sapma_sayisi,
        "bugun_temizlik": bugun_temizlik,
        "CCPKategori": CCPKategori,
        "CCPDurum": CCPDurum,
    })


@router.post("/ccp/ekle")
def ccp_ekle(
    ad: str = Form(...),
    kategori: str = Form(...),
    aciklama: str = Form(""),
    kritik_limit_min: Optional[float] = Form(None),
    kritik_limit_max: Optional[float] = Form(None),
    hedef_deger: str = Form(""),
    birim: str = Form(""),
    olcum_yontemi: str = Form(""),
    duzeltici_eylem: str = Form(""),
    sorumlu_unvan: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(CCPTanim(
        firma_id=user.firma_id, ad=ad, kategori=kategori,
        aciklama=aciklama or None,
        kritik_limit_min=kritik_limit_min,
        kritik_limit_max=kritik_limit_max,
        hedef_deger=hedef_deger or None,
        birim=birim or None,
        olcum_yontemi=olcum_yontemi or None,
        duzeltici_eylem=duzeltici_eylem or None,
        sorumlu_unvan=sorumlu_unvan or None,
    ))
    db.commit()
    return RedirectResponse("/kalite/", status_code=302)


# ═══ CCP ÖLÇÜM ═══════════════════════════════════════════

@router.get("/ccp/olcum", response_class=HTMLResponse)
def olcum_listesi(
    request: Request,
    uretim_id: Optional[int] = Query(None),
    durum: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    q = db.query(CCPOlcum).filter(CCPOlcum.firma_id == fid)
    if uretim_id: q = q.filter(CCPOlcum.uretim_emri_id == uretim_id)
    if durum: q = q.filter(CCPOlcum.durum == durum)
    olcumler = q.order_by(CCPOlcum.olcum_tarihi.desc()).limit(100).all()

    ccp_tanimlar = db.query(CCPTanim).filter(CCPTanim.firma_id == fid, CCPTanim.aktif == True).all()
    uretim_emirleri = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.durum == "devam"
    ).order_by(UretimEmri.created_at.desc()).all()

    return templates.TemplateResponse("kalite/olcum.html", {
        "request": request, "user": user,
        "olcumler": olcumler,
        "ccp_tanimlar": ccp_tanimlar,
        "uretim_emirleri": uretim_emirleri,
        "CCPDurum": CCPDurum,
        "filtre_durum": durum,
    })


@router.post("/ccp/olcum/ekle")
def olcum_ekle(
    ccp_tanim_id: int = Form(...),
    olculen_deger: float = Form(...),
    birim: str = Form(""),
    uretim_emri_id: Optional[int] = Form(None),
    sapma_aciklama: str = Form(""),
    duzeltici_yapildi: Optional[str] = Form(None),
    duzeltici_not: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tanim = db.query(CCPTanim).filter(CCPTanim.id == ccp_tanim_id).first()

    # Durum hesapla
    durum = CCPDurum.uygun
    if tanim:
        val = Decimal(str(olculen_deger))
        if tanim.kritik_limit_min and val < Decimal(str(tanim.kritik_limit_min)):
            durum = CCPDurum.kritik
        elif tanim.kritik_limit_max and val > Decimal(str(tanim.kritik_limit_max)):
            durum = CCPDurum.kritik
        elif sapma_aciklama:
            durum = CCPDurum.sapma

    db.add(CCPOlcum(
        firma_id          = user.firma_id,
        ccp_tanim_id      = ccp_tanim_id,
        uretim_emri_id    = uretim_emri_id or None,
        olculen_deger     = olculen_deger,
        birim             = birim or (tanim.birim if tanim else None),
        durum             = durum,
        sapma_aciklama    = sapma_aciklama or None,
        duzeltici_yapildi = (duzeltici_yapildi == "on"),
        duzeltici_not     = duzeltici_not or None,
        yapan_id          = user.id,
    ))
    db.commit()
    return RedirectResponse("/kalite/ccp/olcum", status_code=302)


# ═══ TEMİZLİK PLANLARI ═══════════════════════════════════

@router.get("/temizlik", response_class=HTMLResponse)
def temizlik_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    planlar = db.query(TemizlikPlan).filter(TemizlikPlan.firma_id == fid, TemizlikPlan.aktif == True).all()
    son_kayitlar = db.query(TemizlikKayit).filter(
        TemizlikKayit.firma_id == fid
    ).order_by(TemizlikKayit.created_at.desc()).limit(30).all()

    return templates.TemplateResponse("kalite/temizlik.html", {
        "request": request, "user": user,
        "planlar": planlar,
        "son_kayitlar": son_kayitlar,
        "TemizlikDurum": TemizlikDurum,
        "now": datetime.now(timezone.utc),
    })


@router.post("/temizlik/plan-ekle")
def temizlik_plan_ekle(
    ad: str = Form(...),
    alan: str = Form(""),
    yontem: str = Form(""),
    kullanilan_kimyasal: str = Form(""),
    siklık: str = Form("Günlük"),
    tahmini_sure: Optional[int] = Form(None),
    sorumlu_unvan: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(TemizlikPlan(
        firma_id=user.firma_id, ad=ad, alan=alan or None,
        yontem=yontem or None,
        kullanilan_kimyasal=kullanilan_kimyasal or None,
        siklık=siklık, tahmini_sure=tahmini_sure,
        sorumlu_unvan=sorumlu_unvan or None,
    ))
    db.commit()
    return RedirectResponse("/kalite/temizlik", status_code=302)


@router.post("/temizlik/kayit-ekle")
def temizlik_kayit_ekle(
    plan_id: Optional[int] = Form(None),
    alan: str = Form(""),
    durum: str = Form("tamamlandı"),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    plan = db.query(TemizlikPlan).filter(TemizlikPlan.id == plan_id).first() if plan_id else None
    db.add(TemizlikKayit(
        firma_id   = user.firma_id,
        plan_id    = plan_id or None,
        alan       = alan or (plan.alan if plan else None),
        durum      = durum,
        baslangic  = now,
        bitis      = now,
        yapan_id   = user.id,
        notlar     = notlar or None,
    ))
    db.commit()
    return RedirectResponse("/kalite/temizlik", status_code=302)
