"""
Faz 4 — Analiz & Akıllı Özellikler
- Allerjen matrisi
- Stok tüketim tahmini (basit hareketli ortalama)
- Raf ömrü simülasyonu
- Ekipman kalibrasyon takibi
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Hammadde, HammaddeLot, Recete, ReceteKalem,
    Urun, UrunParti, UretimEmri, DepoHareket, DepoHareketTip,
    Makine, KalibrasyonKaydi, KalibrasyonDurum,
    StokTuketimKaydi, ALERJEN_LISTESI
)

router = APIRouter(prefix="/analiz", tags=["analiz"])


def _now():
    return datetime.now(timezone.utc)


# ═══ ALLERJEN MATRİSİ ════════════════════════════════════

@router.get("/allerjen", response_class=HTMLResponse)
def allerjen_matrisi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id

    # Tüm hammaddeler ve allerjen bilgileri
    hammaddeler = db.query(Hammadde).filter(
        Hammadde.firma_id == fid, Hammadde.aktif == True
    ).order_by(Hammadde.ad).all()

    # Tüm onaylı reçeteler
    receteler = db.query(Recete).filter(
        Recete.firma_id == fid,
        Recete.onaylandi == True,
        Recete.aktif == True
    ).all()

    # Her reçete için allerjen hesapla
    recete_alerjenler = {}
    for r in receteler:
        alerjen_set = set()
        for k in r.kalemler:
            if k.hammadde and k.hammadde.alerjenler:
                for a in k.hammadde.alerjen_listesi:
                    alerjen_set.add(a)
        recete_alerjenler[r.id] = sorted(alerjen_set)

    # Ürün bazlı allerjen (üretim emri → reçete → allerjenler)
    urunler = db.query(Urun).filter(Urun.firma_id == fid, Urun.aktif == True).all()
    urun_alerjenler = {}
    for u in urunler:
        alerjen_set = set()
        for r in u.receteler:
            if r.id in recete_alerjenler:
                alerjen_set.update(recete_alerjenler[r.id])
        urun_alerjenler[u.id] = sorted(alerjen_set)

    return templates.TemplateResponse("analiz/allerjen.html", {
        "request": request, "user": user,
        "hammaddeler": hammaddeler,
        "receteler": receteler,
        "recete_alerjenler": recete_alerjenler,
        "urunler": urunler,
        "urun_alerjenler": urun_alerjenler,
        "ALERJEN_LISTESI": ALERJEN_LISTESI,
    })


# ═══ STOK TAHMİN ════════════════════════════════════════

@router.get("/stok-tahmin", response_class=HTMLResponse)
def stok_tahmin(
    request: Request,
    hammadde_id: Optional[int] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    hammaddeler = db.query(Hammadde).filter(
        Hammadde.firma_id == fid, Hammadde.aktif == True
    ).order_by(Hammadde.ad).all()

    tahminler = []
    now = _now()

    for h in hammaddeler:
        # Son 30 günlük FIFO çekim verisi
        bas = now - timedelta(days=30)
        cekimler = db.query(DepoHareket).filter(
            DepoHareket.firma_id == fid,
            DepoHareket.tip == DepoHareketTip.cikis,
            DepoHareket.tarih >= bas,
        ).join(HammaddeLot, DepoHareket.lot_id == HammaddeLot.id).filter(
            HammaddeLot.hammadde_id == h.id
        ).all()

        if not cekimler:
            gunluk_ort = Decimal("0")
        else:
            toplam_cekim = sum(float(c.miktar) for c in cekimler)
            gunluk_ort   = Decimal(str(toplam_cekim / 30))

        # Mevcut stok
        mevcut = db.query(func.sum(HammaddeLot.kalan_miktar)).filter(
            HammaddeLot.firma_id == fid,
            HammaddeLot.hammadde_id == h.id,
            HammaddeLot.durum.in_(["onaylı", "kullanımda"])
        ).scalar() or Decimal("0")
        mevcut = Decimal(str(mevcut))

        # Kaç gün yeter?
        gun_yeter = float(mevcut / gunluk_ort) if gunluk_ort > 0 else None
        siparis_tarihi = now + timedelta(days=max(0, (gun_yeter or 0) - 7))

        tahminler.append({
            "hammadde":      h,
            "mevcut":        float(mevcut),
            "gunluk_ort":    float(gunluk_ort),
            "gun_yeter":     round(gun_yeter, 1) if gun_yeter else None,
            "siparis_tarihi": siparis_tarihi if gun_yeter and gun_yeter < 14 else None,
            "kritik":        gun_yeter is not None and gun_yeter < 7,
        })

    # Kritikler önce
    tahminler.sort(key=lambda x: (x["gun_yeter"] or 9999))

    return templates.TemplateResponse("analiz/stok_tahmin.html", {
        "request": request, "user": user,
        "tahminler": tahminler,
        "now": now,
    })


# ═══ RAF ÖMRÜ SİMÜLASYONU ════════════════════════════════

@router.get("/raf-omru", response_class=HTMLResponse)
def raf_omru(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    now = _now()

    # Aktif ürün partileri
    partiler = db.query(UrunParti).filter(
        UrunParti.firma_id == fid,
        UrunParti.kalan_miktar > 0,
    ).order_by(UrunParti.son_kullanma.asc()).all()

    simülasyon = []
    for p in partiler:
        if not p.son_kullanma:
            continue

        # Üretimden pazara kaçıncı günde çıktı?
        uretim_gun = (p.son_kullanma - (p.uretim_tarihi or p.created_at)).days if p.uretim_tarihi else None
        # Kalan raf ömrü
        kalan_gun  = (p.son_kullanma - now).days
        # Toplam raf ömrü
        toplam     = uretim_gun

        simülasyon.append({
            "parti":       p,
            "kalan_gun":   kalan_gun,
            "toplam_gun":  toplam,
            "kullanilan_pct": round((1 - kalan_gun / toplam) * 100, 1) if toplam and toplam > 0 else None,
            "durum":       "kritik" if kalan_gun < 3 else "warn" if kalan_gun < 14 else "ok",
        })

    return templates.TemplateResponse("analiz/raf_omru.html", {
        "request": request, "user": user,
        "simülasyon": simülasyon,
        "now": now,
    })


# ═══ KALİBRASYON TAKİBİ ══════════════════════════════════

@router.get("/kalibrasyon", response_class=HTMLResponse)
def kalibrasyon_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    now = _now()

    # Geçerliliği dolan veya yakında dolacak
    kayitlar = db.query(KalibrasyonKaydi).filter(
        KalibrasyonKaydi.firma_id == fid
    ).order_by(KalibrasyonKaydi.gecerlilik_bitis.asc()).all()

    # Durumları güncelle
    for k in kayitlar:
        if k.gecerlilik_bitis < now:
            k.durum = KalibrasyonDurum.suresi_dolmus
        elif k.gecerlilik_bitis < now + timedelta(days=30):
            pass  # yakında dolacak — uyarı göster
    db.commit()

    makineler = db.query(Makine).filter(Makine.firma_id == fid, Makine.aktif == True).all()

    return templates.TemplateResponse("analiz/kalibrasyon.html", {
        "request": request, "user": user,
        "kayitlar": kayitlar,
        "makineler": makineler,
        "KalibrasyonDurum": KalibrasyonDurum,
        "now": now,
    })


@router.post("/kalibrasyon/ekle")
def kalibrasyon_ekle(
    makine_id: int = Form(...),
    kalibrasyon_no: str = Form(""),
    yapan_kurum: str = Form(""),
    tarih: str = Form(...),
    gecerlilik_bitis: str = Form(...),
    sonuc: str = Form(""),
    belge_no: str = Form(""),
    maliyet: Optional[float] = Form(None),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    def parse_dt(s):
        try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except: return datetime.now(timezone.utc)

    db.add(KalibrasyonKaydi(
        firma_id         = user.firma_id,
        makine_id        = makine_id,
        kalibrasyon_no   = kalibrasyon_no or None,
        yapan_kurum      = yapan_kurum or None,
        tarih            = parse_dt(tarih),
        gecerlilik_bitis = parse_dt(gecerlilik_bitis),
        durum            = KalibrasyonDurum.gecerli,
        sonuc            = sonuc or None,
        belge_no         = belge_no or None,
        maliyet          = maliyet,
        notlar           = notlar or None,
        created_by       = user.id,
    ))
    db.commit()
    return RedirectResponse("/analiz/kalibrasyon", status_code=302)
