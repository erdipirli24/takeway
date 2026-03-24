from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Musteri, SatisEmri, SatisKalem, Sevkiyat, SevkiyatKalem,
    SiparisDurum, UrunParti, Urun
)
from app.utils.helpers import qr_olustur

router = APIRouter(prefix="/satis", tags=["satis"])
templates = Jinja2Templates(directory="app/templates")


def _siparis_no(db: Session, firma_id: int) -> str:
    sira = db.query(SatisEmri).filter(SatisEmri.firma_id == firma_id).count() + 1
    return f"SP-{firma_id:02d}-{datetime.now().strftime('%y%m')}-{sira:04d}"


def _sevk_no(db: Session, firma_id: int) -> str:
    sira = db.query(Sevkiyat).filter(Sevkiyat.firma_id == firma_id).count() + 1
    return f"SV-{firma_id:02d}-{datetime.now().strftime('%y%m%d')}-{sira:04d}"


def _parse_dt(s):
    if s:
        try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except: pass
    return None


# ═══ MÜŞTERİLER ══════════════════════════════════════════

@router.get("/musteri", response_class=HTMLResponse)
def musteri_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    musteriler = db.query(Musteri).filter(
        Musteri.firma_id == user.firma_id, Musteri.aktif == True
    ).order_by(Musteri.ad).all()
    return templates.TemplateResponse("satis/musteri.html", {
        "request": request, "user": user, "musteriler": musteriler
    })


@router.post("/musteri/ekle")
def musteri_ekle(
    ad: str = Form(...), kod: str = Form(""),
    vergi_no: str = Form(""), email: str = Form(""),
    telefon: str = Form(""), adres: str = Form(""),
    sehir: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(Musteri(
        firma_id=user.firma_id, ad=ad, kod=kod or None,
        vergi_no=vergi_no or None, email=email or None,
        telefon=telefon or None, adres=adres or None, sehir=sehir or None
    ))
    db.commit()
    return RedirectResponse("/satis/musteri", status_code=302)


# ═══ SİPARİŞLER ══════════════════════════════════════════

@router.get("/siparis", response_class=HTMLResponse)
def siparis_listesi(
    request: Request,
    durum: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    q = db.query(SatisEmri).filter(SatisEmri.firma_id == fid)
    if durum: q = q.filter(SatisEmri.durum == durum)
    siparisler = q.order_by(SatisEmri.created_at.desc()).all()
    musteriler = db.query(Musteri).filter(Musteri.firma_id == fid, Musteri.aktif == True).all()
    urunler    = db.query(Urun).filter(Urun.firma_id == fid, Urun.aktif == True).all()

    return templates.TemplateResponse("satis/siparis_liste.html", {
        "request": request, "user": user,
        "siparisler": siparisler,
        "musteriler": musteriler,
        "urunler": urunler,
        "SiparisDurum": SiparisDurum,
        "filtre_durum": durum,
    })


@router.post("/siparis/ekle")
def siparis_ekle(
    musteri_id: int = Form(...),
    istenen_termin: Optional[str] = Form(None),
    sevk_adresi: str = Form(""),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    no = _siparis_no(db, user.firma_id)
    sp = SatisEmri(
        firma_id       = user.firma_id,
        musteri_id     = musteri_id,
        siparis_no     = no,
        durum          = SiparisDurum.taslak,
        istenen_termin = _parse_dt(istenen_termin),
        sevk_adresi    = sevk_adresi or None,
        notlar         = notlar or None,
        created_by     = user.id,
    )
    db.add(sp); db.commit(); db.refresh(sp)
    return RedirectResponse(f"/satis/siparis/{sp.id}", status_code=302)


@router.get("/siparis/{sid}", response_class=HTMLResponse)
def siparis_detay(
    sid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sp = db.query(SatisEmri).filter(SatisEmri.id == sid, SatisEmri.firma_id == user.firma_id).first()
    if not sp: return RedirectResponse("/satis/siparis", status_code=302)

    # Kullanılabilir ürün partileri
    partiler = db.query(UrunParti).filter(
        UrunParti.firma_id == user.firma_id,
        UrunParti.kalan_miktar > 0
    ).order_by(UrunParti.uretim_tarihi.desc()).all()

    urunler = db.query(Urun).filter(Urun.firma_id == user.firma_id, Urun.aktif == True).all()

    return templates.TemplateResponse("satis/siparis_detay.html", {
        "request": request, "user": user,
        "sp": sp, "partiler": partiler, "urunler": urunler,
        "SiparisDurum": SiparisDurum,
    })


@router.post("/siparis/{sid}/kalem-ekle")
def kalem_ekle(
    sid: int,
    urun_parti_id: Optional[int] = Form(None),
    urun_id: Optional[int] = Form(None),
    aciklama: str = Form(""),
    miktar: float = Form(...),
    birim: str = Form("kg"),
    birim_fiyat: Optional[float] = Form(None),
    kdv_oran: float = Form(10),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    toplam = (miktar * (birim_fiyat or 0)) * (1 + kdv_oran / 100)
    db.add(SatisKalem(
        siparis_id    = sid,
        urun_parti_id = urun_parti_id or None,
        urun_id       = urun_id or None,
        aciklama      = aciklama or None,
        miktar        = miktar,
        birim         = birim,
        birim_fiyat   = birim_fiyat,
        kdv_oran      = kdv_oran,
        toplam        = round(toplam, 2) if birim_fiyat else None,
    ))
    db.commit()
    return RedirectResponse(f"/satis/siparis/{sid}", status_code=302)


@router.post("/siparis/{sid}/durum")
def siparis_durum(
    sid: int,
    durum: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sp = db.query(SatisEmri).filter(SatisEmri.id == sid, SatisEmri.firma_id == user.firma_id).first()
    if sp:
        sp.durum = durum
        db.commit()
    return RedirectResponse(f"/satis/siparis/{sid}", status_code=302)


# ═══ SEVKİYAT ════════════════════════════════════════════

@router.get("/sevkiyat", response_class=HTMLResponse)
def sevkiyat_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sevkiyatlar = db.query(Sevkiyat).filter(
        Sevkiyat.firma_id == user.firma_id
    ).order_by(Sevkiyat.created_at.desc()).all()

    # Hazırlanmayı bekleyen siparişler
    bekleyen = db.query(SatisEmri).filter(
        SatisEmri.firma_id == user.firma_id,
        SatisEmri.durum == SiparisDurum.onaylı
    ).all()

    partiler = db.query(UrunParti).filter(
        UrunParti.firma_id == user.firma_id,
        UrunParti.kalan_miktar > 0
    ).order_by(UrunParti.uretim_tarihi.desc()).all()

    return templates.TemplateResponse("satis/sevkiyat_liste.html", {
        "request": request, "user": user,
        "sevkiyatlar": sevkiyatlar,
        "bekleyen": bekleyen,
        "partiler": partiler,
    })


@router.post("/sevkiyat/olustur")
def sevkiyat_olustur(
    siparis_id: Optional[int] = Form(None),
    sevk_tarihi: Optional[str] = Form(None),
    nakliyeci: str = Form(""),
    plaka: str = Form(""),
    sofor: str = Form(""),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    no  = _sevk_no(db, fid)
    qr  = qr_olustur(f"TW-SEVKİYAT\nNo: {no}\nTarih: {sevk_tarihi or ''}\nNakliyeci: {nakliyeci}")

    sv = Sevkiyat(
        firma_id   = fid,
        siparis_id = siparis_id or None,
        sevk_no    = no,
        sevk_tarihi = _parse_dt(sevk_tarihi),
        nakliyeci  = nakliyeci or None,
        plaka      = plaka or None,
        sofor      = sofor or None,
        notlar     = notlar or None,
        qr_data    = qr,
        created_by = user.id,
    )
    db.add(sv); db.flush()

    # Sipariş kalemlerinden otomatik sevkiyat kalemi oluştur
    if siparis_id:
        sp = db.query(SatisEmri).filter(SatisEmri.id == siparis_id).first()
        if sp:
            for k in sp.kalemler:
                if k.urun_parti_id:
                    db.add(SevkiyatKalem(
                        sevkiyat_id   = sv.id,
                        urun_parti_id = k.urun_parti_id,
                        miktar        = k.miktar,
                        birim         = k.birim,
                    ))
                    # Parti stoğunu düş
                    parti = db.query(UrunParti).filter(UrunParti.id == k.urun_parti_id).first()
                    if parti:
                        parti.kalan_miktar = max(0, float(parti.kalan_miktar) - float(k.miktar))
            sp.durum = SiparisDurum.sevkedildi

    db.commit()
    return RedirectResponse(f"/satis/sevkiyat/{sv.id}", status_code=302)


@router.get("/sevkiyat/{svid}", response_class=HTMLResponse)
def sevkiyat_detay(
    svid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sv = db.query(Sevkiyat).filter(Sevkiyat.id == svid, Sevkiyat.firma_id == user.firma_id).first()
    if not sv: return RedirectResponse("/satis/sevkiyat", status_code=302)

    partiler = db.query(UrunParti).filter(
        UrunParti.firma_id == user.firma_id,
        UrunParti.kalan_miktar > 0
    ).all()

    return templates.TemplateResponse("satis/sevkiyat_detay.html", {
        "request": request, "user": user,
        "sv": sv, "partiler": partiler,
    })


@router.post("/sevkiyat/{svid}/kalem-ekle")
def sevk_kalem_ekle(
    svid: int,
    urun_parti_id: int = Form(...),
    miktar: float = Form(...),
    birim: str = Form("kg"),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.add(SevkiyatKalem(
        sevkiyat_id=svid, urun_parti_id=urun_parti_id,
        miktar=miktar, birim=birim
    ))
    # Parti stoğu düş
    parti = db.query(UrunParti).filter(UrunParti.id == urun_parti_id).first()
    if parti:
        parti.kalan_miktar = max(0, float(parti.kalan_miktar) - miktar)
    db.commit()
    return RedirectResponse(f"/satis/sevkiyat/{svid}", status_code=302)


@router.post("/sevkiyat/{svid}/teslim")
def sevkiyat_teslim(
    svid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sv = db.query(Sevkiyat).filter(Sevkiyat.id == svid, Sevkiyat.firma_id == user.firma_id).first()
    if sv:
        sv.gercek_teslim = datetime.now(timezone.utc)
        if sv.siparis_id:
            sp = db.query(SatisEmri).filter(SatisEmri.id == sv.siparis_id).first()
            if sp: sp.durum = SiparisDurum.teslim
        db.commit()
    return RedirectResponse(f"/satis/sevkiyat/{svid}", status_code=302)
