"""
Sistem Yönetimi
- Firma ayarları
- Bildirim merkezi
- API anahtarı yönetimi
- Denetim izi (audit log)
- Performans dashboard
"""
import secrets
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Firma, SistemAyar, BildirimKaydi, ApiAnahtari, DenetimIzi,
    HammaddeLot, UretimEmri, UrunParti, Sikayet, Numune,
    LotDurum, UretimDurum, NumuneDurum, SikayetDurum,
    DepoHareket, CCPOlcum, CCPDurum
)
from app.utils.bildirim import tum_kontrolleri_calistir, okunmamis_sayisi

router = APIRouter(prefix="/sistem", tags=["sistem"])


# ═══ PERFORMANS DASHBOARD ════════════════════════════════

@router.get("/performans", response_class=HTMLResponse)
def performans(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    now = datetime.now(timezone.utc)

    # Son 30 gün
    bas30 = now - timedelta(days=30)
    bas7  = now - timedelta(days=7)

    # Üretim metrikleri
    toplam_uretim_30 = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.created_at >= bas30
    ).count()

    tamamlanan_30 = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.durum == UretimDurum.tamamlandı,
        UretimEmri.bitis >= bas30
    ).count()

    # Kalite uyum oranı
    ccp_toplam = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == fid,
        CCPOlcum.olcum_tarihi >= bas30
    ).count()
    ccp_uygun = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == fid,
        CCPOlcum.durum == CCPDurum.uygun,
        CCPOlcum.olcum_tarihi >= bas30
    ).count()
    uyum_orani = round(ccp_uygun / ccp_toplam * 100, 1) if ccp_toplam else 100

    # Lot girişi ve karantina oranı
    lot_giris_30 = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == fid,
        HammaddeLot.kabul_tarihi >= bas30
    ).count()
    lot_karantina_30 = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == fid,
        HammaddeLot.durum == LotDurum.karantina,
        HammaddeLot.kabul_tarihi >= bas30
    ).count()

    # Bekleyen numune
    bekleyen_numune = db.query(Numune).filter(
        Numune.firma_id == fid,
        Numune.durum == NumuneDurum.beklemede
    ).count()

    # Açık şikayet
    acik_sikayet = db.query(Sikayet).filter(
        Sikayet.firma_id == fid,
        Sikayet.durum != SikayetDurum.kapatildi
    ).count()

    # Son 7 günlük günlük üretim trendi (basit)
    gunluk_trend = []
    for i in range(7, 0, -1):
        gun_bas = now - timedelta(days=i)
        gun_bit = now - timedelta(days=i-1)
        sayi = db.query(UretimEmri).filter(
            UretimEmri.firma_id == fid,
            UretimEmri.created_at >= gun_bas,
            UretimEmri.created_at < gun_bit,
        ).count()
        gunluk_trend.append({
            "tarih": gun_bas.strftime("%d.%m"),
            "sayi": sayi
        })

    # Bildirimler kontrolü
    tum_kontrolleri_calistir(db, fid)

    return templates.TemplateResponse("sistem/performans.html", {
        "request": request, "user": user,
        "toplam_uretim_30": toplam_uretim_30,
        "tamamlanan_30": tamamlanan_30,
        "uyum_orani": uyum_orani,
        "lot_giris_30": lot_giris_30,
        "lot_karantina_30": lot_karantina_30,
        "bekleyen_numune": bekleyen_numune,
        "acik_sikayet": acik_sikayet,
        "gunluk_trend": gunluk_trend,
        "ccp_toplam": ccp_toplam,
        "now": now,
    })


# ═══ BİLDİRİMLER ════════════════════════════════════════

@router.get("/bildirimler", response_class=HTMLResponse)
def bildirimler(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    tum_kontrolleri_calistir(db, fid)

    bildirimler_list = db.query(BildirimKaydi).filter(
        BildirimKaydi.firma_id == fid
    ).order_by(BildirimKaydi.created_at.desc()).limit(50).all()

    return templates.TemplateResponse("sistem/bildirimler.html", {
        "request": request, "user": user,
        "bildirimler": bildirimler_list,
        "okunmamis": okunmamis_sayisi(db, fid),
    })


@router.post("/bildirimler/tumu-oku")
def tumu_oku(
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(BildirimKaydi).filter(
        BildirimKaydi.firma_id == user.firma_id,
        BildirimKaydi.okundu == False
    ).update({"okundu": True})
    db.commit()
    return RedirectResponse("/sistem/bildirimler", status_code=302)


@router.get("/bildirimler/sayac")
def bildirim_sayac(
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return JSONResponse({"sayi": okunmamis_sayisi(db, user.firma_id)})


# ═══ SİSTEM AYARLARI ════════════════════════════════════

VARSAYILAN_AYARLAR = {
    "skt_uyari_gun": ("30", "Son kullanma tarihi kaç gün öncesinden uyarı verilsin"),
    "kritik_stok_uyari": ("true", "Kritik stok seviyesinde uyarı ver"),
    "numune_bekle_saat": ("48", "Numune onayı kaç saat beklenirse uyarı verilsin"),
    "fifo_zorunlu": ("true", "FIFO kuralını zorla"),
    "raf_omru_uyari_gun": ("7", "Ürün partisi SKT kaç gün önceden uyarı"),
    "firma_adres": ("", "Etiketlerde görünecek firma adresi"),
    "firma_tel": ("", "Etiketlerde görünecek firma telefonu"),
    "kalibrasyon_uyari_gun": ("30", "Kalibrasyon bitimine kaç gün kala uyarı"),
}


@router.get("/ayarlar", response_class=HTMLResponse)
def ayarlar(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    fid = user.firma_id
    # Mevcut ayarları getir, eksik olanlar için varsayılan değer kullan
    mevcut = {a.anahtar: a.deger for a in db.query(SistemAyar).filter(SistemAyar.firma_id == fid).all()}
    ayarlar_dict = {}
    for k, (v, aciklama) in VARSAYILAN_AYARLAR.items():
        ayarlar_dict[k] = {"deger": mevcut.get(k, v), "aciklama": aciklama}

    api_anahtarlari = db.query(ApiAnahtari).filter(ApiAnahtari.firma_id == fid).all()

    return templates.TemplateResponse("sistem/ayarlar.html", {
        "request": request, "user": user,
        "ayarlar": ayarlar_dict,
        "api_anahtarlari": api_anahtarlari,
    })


@router.post("/ayarlar/kaydet")
async def ayarlar_kaydet(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    form = await request.form()
    fid  = user.firma_id

    for k in VARSAYILAN_AYARLAR:
        deger = form.get(k, "")
        mevcut = db.query(SistemAyar).filter(
            SistemAyar.firma_id == fid,
            SistemAyar.anahtar == k
        ).first()
        if mevcut:
            mevcut.deger = deger
        else:
            db.add(SistemAyar(firma_id=fid, anahtar=k, deger=deger))

    db.commit()
    return RedirectResponse("/sistem/ayarlar", status_code=302)


# ═══ API ANAHTARLARI ════════════════════════════════════

@router.post("/api-anahtari/olustur")
def api_anahtari_olustur(
    ad: str = Form(...),
    izinler: str = Form("read"),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    anahtar = secrets.token_hex(32)
    db.add(ApiAnahtari(
        firma_id   = user.firma_id,
        ad         = ad,
        anahtar    = anahtar,
        izinler    = izinler,
        created_by = user.id,
    ))
    db.commit()
    return RedirectResponse("/sistem/ayarlar", status_code=302)


@router.post("/api-anahtari/{aid}/iptal")
def api_anahtari_iptal(
    aid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    a = db.query(ApiAnahtari).filter(
        ApiAnahtari.id == aid, ApiAnahtari.firma_id == user.firma_id
    ).first()
    if a:
        a.aktif = False
        db.commit()
    return RedirectResponse("/sistem/ayarlar", status_code=302)


# ═══ DENETİM İZİ ════════════════════════════════════════

@router.get("/denetim-izi", response_class=HTMLResponse)
def denetim_izi(
    request: Request,
    islem: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/", status_code=302)

    q = db.query(DenetimIzi).filter(DenetimIzi.firma_id == user.firma_id)
    if islem:
        q = q.filter(DenetimIzi.islem == islem)
    kayitlar = q.order_by(DenetimIzi.tarih.desc()).limit(100).all()

    return templates.TemplateResponse("sistem/denetim_izi.html", {
        "request": request, "user": user,
        "kayitlar": kayitlar,
        "filtre_islem": islem,
    })


# ═══ REST API ENDPOINTLER ════════════════════════════════

@router.get("/api/v1/stok", response_class=JSONResponse)
def api_stok(
    request: Request,
    api_key: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Harici sistemler için stok API'si."""
    if not api_key:
        return JSONResponse({"hata": "API anahtarı gerekli"}, status_code=401)

    anahtar = db.query(ApiAnahtari).filter(
        ApiAnahtari.anahtar == api_key,
        ApiAnahtari.aktif == True
    ).first()
    if not anahtar:
        return JSONResponse({"hata": "Geçersiz API anahtarı"}, status_code=401)

    # Son kullanım güncelle
    anahtar.son_kullanim = datetime.now(timezone.utc)
    db.commit()

    lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == anahtar.firma_id,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda])
    ).order_by(HammaddeLot.hammadde_id, HammaddeLot.kabul_tarihi).all()

    return JSONResponse({
        "firma_id": anahtar.firma_id,
        "tarih": datetime.now(timezone.utc).isoformat(),
        "stok": [
            {
                "hammadde": l.hammadde.ad,
                "hammadde_kod": l.hammadde.kod,
                "ic_parti_no": l.ic_parti_no,
                "lot_no": l.lot_no,
                "kalan_miktar": float(l.kalan_miktar),
                "birim": l.hammadde.birim,
                "son_kullanma": l.son_kullanma.isoformat() if l.son_kullanma else None,
                "durum": l.durum.value,
                "fifo_sira": l.fifo_sira,
            }
            for l in lotlar
        ]
    })


@router.get("/api/v1/izlenebilirlik/{parti_no}", response_class=JSONResponse)
def api_izlenebilirlik(
    parti_no: str,
    api_key: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Parti numarası ile izlenebilirlik verisi."""
    if not api_key:
        return JSONResponse({"hata": "API anahtarı gerekli"}, status_code=401)

    anahtar = db.query(ApiAnahtari).filter(
        ApiAnahtari.anahtar == api_key, ApiAnahtari.aktif == True
    ).first()
    if not anahtar:
        return JSONResponse({"hata": "Geçersiz API anahtarı"}, status_code=401)

    parti = db.query(UrunParti).filter(
        UrunParti.firma_id == anahtar.firma_id,
        UrunParti.parti_no == parti_no
    ).first()
    if not parti:
        return JSONResponse({"hata": "Parti bulunamadı"}, status_code=404)

    from app.models.models import UretimHammadde
    kullanim = db.query(UretimHammadde).filter(
        UretimHammadde.emir_id == parti.uretim_emri_id
    ).all() if parti.uretim_emri_id else []

    return JSONResponse({
        "parti_no": parti.parti_no,
        "urun": parti.urun.ad if parti.urun else None,
        "uretim_tarihi": parti.uretim_tarihi.isoformat() if parti.uretim_tarihi else None,
        "son_kullanma": parti.son_kullanma.isoformat() if parti.son_kullanma else None,
        "miktar": float(parti.uretim_miktari),
        "birim": parti.birim,
        "uretim_emri": parti.uretim_emri.emri_no if parti.uretim_emri else None,
        "hammadde_lotlari": [
            {
                "ic_parti_no": k.lot.ic_parti_no if k.lot else None,
                "lot_no": k.lot.lot_no if k.lot else None,
                "hammadde": k.lot.hammadde.ad if k.lot else None,
                "tedarikci": k.lot.tedarikci.ad if k.lot and k.lot.tedarikci else None,
                "fatura_no": k.lot.fatura_no if k.lot else None,
                "kullanilan": float(k.kullanilan),
                "fifo_sira": k.fifo_sira,
            }
            for k in kullanim
        ]
    })
