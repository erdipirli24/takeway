from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates, safe_float, safe_int
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.auth import get_current_user, hash_password, tum_yetkiler_olustur
from app.models.models import Firma, Kullanici, FirmaTip, BirimTanim
from app.utils.helpers import firma_kodu_olustur

router = APIRouter(prefix="/firma", tags=["firma"])


# ─── FİRMA PANELİ (süper admin) ──────────────────────────
@router.get("/", response_class=HTMLResponse)
def firma_listesi(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_super:
        return RedirectResponse("/", status_code=302)
    firmalar = db.query(Firma).filter(Firma.parent_id == None).order_by(Firma.id).all()
    return templates.TemplateResponse("firma/liste.html", {
        "request": request, "user": user, "firmalar": firmalar
    })


@router.post("/ekle")
def firma_ekle(
    ad: str = Form(...),
    slug: str = Form(...),
    vergi_no: str = Form(""),
    sehir: str = Form(""),
    email: str = Form(""),
    telefon: str = Form(""),
    adres: str = Form(""),
    # İlk admin bilgileri
    admin_ad: str = Form(...),
    admin_email: str = Form(...),
    admin_sifre: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user.is_super:
        return RedirectResponse("/", status_code=302)

    # Firma kodu: mevcut max id + 1
    max_id = db.query(Firma).count() + 1
    kod    = str(max_id)

    firma = Firma(
        firma_kodu = kod,
        tip        = FirmaTip.merkez,
        ad         = ad,
        slug       = slug,
        vergi_no   = vergi_no or None,
        sehir      = sehir or None,
        email      = email or None,
        telefon    = telefon or None,
        adres      = adres or None,
    )
    db.add(firma); db.flush()

    # Firma admini oluştur
    admin = Kullanici(
        firma_id      = firma.id,
        ad_soyad      = admin_ad,
        email         = admin_email,
        hashed_pw     = hash_password(admin_sifre),
        is_firma_admin = True,
        aktif         = True,
    )
    db.add(admin); db.flush()
    tum_yetkiler_olustur(db, admin.id, firma_admin=True)

    db.commit()
    return RedirectResponse("/firma/", status_code=302)


# ─── ŞUBE EKLE ───────────────────────────────────────────
@router.post("/{fid}/sube-ekle")
def sube_ekle(
    fid: int,
    ad: str = Form(...),
    slug: str = Form(...),
    sehir: str = Form(""),
    adres: str = Form(""),
    admin_ad: str = Form(...),
    admin_email: str = Form(...),
    admin_sifre: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    parent = db.query(Firma).filter(Firma.id == fid).first()
    if not parent:
        return RedirectResponse("/firma/", status_code=302)

    # Şube sırasını belirle
    mevcut_sube = db.query(Firma).filter(Firma.parent_id == fid).count()
    kod = firma_kodu_olustur(parent.firma_kodu, mevcut_sube + 1)

    sube = Firma(
        parent_id  = fid,
        tip        = FirmaTip.sube,
        firma_kodu = kod,
        ad         = f"{parent.ad} — {ad}",
        slug       = slug,
        sehir      = sehir or None,
        adres      = adres or None,
    )
    db.add(sube); db.flush()

    admin = Kullanici(
        firma_id       = sube.id,
        ad_soyad       = admin_ad,
        email          = admin_email,
        hashed_pw      = hash_password(admin_sifre),
        is_firma_admin = True,
        aktif          = True,
    )
    db.add(admin); db.flush()
    tum_yetkiler_olustur(db, admin.id, firma_admin=True)

    db.commit()
    return RedirectResponse("/firma/", status_code=302)


# ─── AYARLAR (firma admini) ───────────────────────────────
@router.get("/ayarlar", response_class=HTMLResponse)
def ayarlar(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)
    firma   = db.query(Firma).filter(Firma.id == user.firma_id).first()
    birimler = db.query(BirimTanim).filter(BirimTanim.firma_id == user.firma_id).all()
    return templates.TemplateResponse("firma/ayarlar.html", {
        "request": request, "user": user, "firma": firma, "birimler": birimler
    })


@router.post("/ayarlar/birim-ekle")
def birim_ekle(
    ad: str = Form(...),
    kisaltma: str = Form(""),
    kg_karsiligi: str = Form(""),
    adet_karsiligi: str = Form(""),
    aciklama: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    b = BirimTanim(
        firma_id       = user.firma_id,
        ad             = ad,
        kisaltma       = kisaltma or None,
        kg_karsiligi   = safe_float(kg_karsiligi),
        adet_karsiligi = safe_float(adet_karsiligi),
        aciklama       = aciklama or None,
    )
    db.add(b); db.commit()
    return RedirectResponse("/firma/ayarlar", status_code=302)
