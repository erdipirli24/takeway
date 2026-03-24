from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.auth import get_current_user, hash_password, tum_yetkiler_olustur
from app.models.models import Kullanici, KullaniciYetki, Modul

router = APIRouter(prefix="/kullanici", tags=["kullanici"])
templates = Jinja2Templates(directory="app/templates")

MODUL_ETIKETLER = {
    Modul.dashboard:       "Dashboard",
    Modul.depo_stok:       "Depo & Stok",
    Modul.hammadde_giris:  "Hammadde Girişi",
    Modul.uretim:          "Üretim Emirleri",
    Modul.recete:          "Reçete Görüntüleme",
    Modul.recete_duzenle:  "Reçete Düzenleme",
    Modul.karisim:         "Karışım Modu",
    Modul.kalite_numune:   "Kalite & Numune",
    Modul.makine:          "Makine Yönetimi",
    Modul.satis_sevkiyat:  "Satış & Sevkiyat",
    Modul.sikayet_recall:  "Şikayet & Recall",
    Modul.raporlar:        "Raporlar",
    Modul.kullanici_yonet: "Kullanıcı Yönetimi",
    Modul.firma_ayarlar:   "Firma Ayarları",
}


@router.get("/", response_class=HTMLResponse)
def kullanici_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    kullanicilar = db.query(Kullanici).filter(
        Kullanici.firma_id == user.firma_id,
        Kullanici.aktif == True
    ).order_by(Kullanici.ad_soyad).all()

    return templates.TemplateResponse("kullanici/liste.html", {
        "request": request, "user": user,
        "kullanicilar": kullanicilar,
        "MODUL_ETIKETLER": MODUL_ETIKETLER,
    })


@router.post("/ekle")
def kullanici_ekle(
    ad_soyad: str = Form(...),
    unvan: str = Form(""),
    email: str = Form(...),
    sifre: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    yeni = Kullanici(
        firma_id      = user.firma_id,
        ad_soyad      = ad_soyad,
        unvan         = unvan or None,
        email         = email,
        hashed_pw     = hash_password(sifre),
        is_firma_admin = False,
        aktif         = True,
    )
    db.add(yeni); db.flush()
    # Boş yetki matrisi oluştur
    tum_yetkiler_olustur(db, yeni.id, firma_admin=False)
    db.commit()
    return RedirectResponse(f"/kullanici/{yeni.id}/yetki", status_code=302)


@router.get("/{kid}/yetki", response_class=HTMLResponse)
def yetki_sayfasi(
    kid: int,
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    hedef = db.query(Kullanici).filter(
        Kullanici.id == kid,
        Kullanici.firma_id == user.firma_id
    ).first()
    if not hedef:
        return RedirectResponse("/kullanici/", status_code=302)

    # Yetki matrisini modül sırasıyla getir
    yetkiler = {
        y.modul: y
        for y in db.query(KullaniciYetki).filter(KullaniciYetki.kullanici_id == kid).all()
    }

    return templates.TemplateResponse("kullanici/yetki.html", {
        "request": request, "user": user,
        "hedef": hedef,
        "moduller": list(Modul),
        "yetkiler": yetkiler,
        "MODUL_ETIKETLER": MODUL_ETIKETLER,
    })


@router.post("/{kid}/yetki-kaydet")
async def yetki_kaydet(
    kid: int,
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    form = await request.form()

    for modul in Modul:
        yetki = db.query(KullaniciYetki).filter(
            KullaniciYetki.kullanici_id == kid,
            KullaniciYetki.modul == modul
        ).first()
        if not yetki:
            yetki = KullaniciYetki(kullanici_id=kid, modul=modul)
            db.add(yetki)

        yetki.gorebilir       = f"gor_{modul.value}"  in form
        yetki.giris_yapabilir = f"gir_{modul.value}" in form

    db.commit()
    return RedirectResponse(f"/kullanici/{kid}/yetki", status_code=302)


@router.post("/{kid}/sifre-sifirla")
def sifre_sifirla(
    kid: int,
    yeni_sifre: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)
    hedef = db.query(Kullanici).filter(Kullanici.id == kid, Kullanici.firma_id == user.firma_id).first()
    if hedef:
        hedef.hashed_pw = hash_password(yeni_sifre)
        db.commit()
    return RedirectResponse("/kullanici/", status_code=302)


@router.post("/{kid}/pasif")
def kullanici_pasif(
    kid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)
    hedef = db.query(Kullanici).filter(Kullanici.id == kid, Kullanici.firma_id == user.firma_id).first()
    if hedef and hedef.id != user.id:
        hedef.aktif = False
        db.commit()
    return RedirectResponse("/kullanici/", status_code=302)
