from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, HammaddeLot, UretimEmri, UretimHammadde,
    UrunParti, Sevkiyat, SevkiyatKalem, Sikayet,
    LotDurum, DepoHareket, DepoHareketTip,
    CCPOlcum, CCPDurum, Tedarikci, Hammadde,
    YariMamul, YariMamulDurum
)

router = APIRouter(prefix="/rapor", tags=["rapor"])
templates = Jinja2Templates(directory="app/templates")


def _now():
    return datetime.now(timezone.utc)


# ═══ RAPOR ANA SAYFASI ═══════════════════════════════════

@router.get("/", response_class=HTMLResponse)
def rapor_anasayfa(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return templates.TemplateResponse("rapor/anasayfa.html", {
        "request": request, "user": user,
    })


# ═══ İZLENEBİLİRLİK RAPORU ═══════════════════════════════

@router.get("/izlenebilirlik", response_class=HTMLResponse)
def izlenebilirlik(
    request: Request,
    parti_no: Optional[str] = Query(None),
    lot_no: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid    = user.firma_id
    sonuc  = None
    tip    = None

    if parti_no:
        # Parti numarasından geriye iz
        parti = db.query(UrunParti).filter(
            UrunParti.firma_id == fid,
            UrunParti.parti_no.ilike(f"%{parti_no}%")
        ).first()
        if parti:
            emir = parti.uretim_emri
            kullanim = db.query(UretimHammadde).filter(
                UretimHammadde.emir_id == emir.id
            ).order_by(UretimHammadde.fifo_sira).all() if emir else []

            # Sevkiyatlar
            sevk_kalemler = db.query(SevkiyatKalem).filter(
                SevkiyatKalem.urun_parti_id == parti.id
            ).all()

            # Şikayetler
            sikayetler = db.query(Sikayet).filter(
                Sikayet.urun_parti_id == parti.id
            ).all()

            sonuc = {
                "parti": parti,
                "emir": emir,
                "kullanim": kullanim,
                "sevk_kalemler": sevk_kalemler,
                "sikayetler": sikayetler,
            }
            tip = "parti"

    elif lot_no:
        # Lot numarasından ileriye iz
        lot = db.query(HammaddeLot).filter(
            HammaddeLot.firma_id == fid,
            (HammaddeLot.lot_no.ilike(f"%{lot_no}%")) |
            (HammaddeLot.ic_parti_no.ilike(f"%{lot_no}%"))
        ).first()
        if lot:
            kullanim = db.query(UretimHammadde).filter(
                UretimHammadde.lot_id == lot.id
            ).all()
            emirler = list({k.emir for k in kullanim if k.emir})
            partiler = []
            for e in emirler:
                partiler.extend(e.urun_partiler)

            sonuc = {
                "lot": lot,
                "kullanim": kullanim,
                "emirler": emirler,
                "partiler": partiler,
            }
            tip = "lot"

    return templates.TemplateResponse("rapor/izlenebilirlik.html", {
        "request": request, "user": user,
        "parti_no": parti_no or "",
        "lot_no": lot_no or "",
        "sonuc": sonuc,
        "tip": tip,
    })


# ═══ HACCP RAPORU ════════════════════════════════════════

@router.get("/haccp", response_class=HTMLResponse)
def haccp_raporu(
    request: Request,
    baslangic: Optional[str] = Query(None),
    bitis: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    now = _now()

    bas_dt = datetime.strptime(baslangic, "%Y-%m-%d").replace(tzinfo=timezone.utc) if baslangic else now - timedelta(days=30)
    bit_dt = datetime.strptime(bitis, "%Y-%m-%d").replace(tzinfo=timezone.utc) if bitis else now

    olcumler = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == fid,
        CCPOlcum.olcum_tarihi >= bas_dt,
        CCPOlcum.olcum_tarihi <= bit_dt,
    ).order_by(CCPOlcum.olcum_tarihi.desc()).all()

    toplam    = len(olcumler)
    uygun     = sum(1 for o in olcumler if o.durum == CCPDurum.uygun)
    sapma     = sum(1 for o in olcumler if o.durum == CCPDurum.sapma)
    kritik    = sum(1 for o in olcumler if o.durum == CCPDurum.kritik)
    uyum_orani = round((uygun / toplam * 100), 1) if toplam else 0

    return templates.TemplateResponse("rapor/haccp.html", {
        "request": request, "user": user,
        "olcumler": olcumler,
        "toplam": toplam, "uygun": uygun,
        "sapma": sapma, "kritik": kritik,
        "uyum_orani": uyum_orani,
        "baslangic": baslangic or bas_dt.strftime("%Y-%m-%d"),
        "bitis": bitis or bit_dt.strftime("%Y-%m-%d"),
    })


# ═══ TEDARİKÇİ PERFORMANS ════════════════════════════════

@router.get("/tedarikci", response_class=HTMLResponse)
def tedarikci_raporu(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    tedarikciler = db.query(Tedarikci).filter(
        Tedarikci.firma_id == fid, Tedarikci.aktif == True
    ).all()

    # Her tedarikçi için detaylı metrik
    metrikler = []
    for t in tedarikciler:
        lotlar = db.query(HammaddeLot).filter(HammaddeLot.tedarikci_id == t.id).all()
        toplam   = len(lotlar)
        karantina = sum(1 for l in lotlar if l.durum == LotDurum.karantina)
        iade      = sum(1 for l in lotlar if l.durum == LotDurum.iade)
        puan      = max(0, 100 - (karantina + iade * 2) / max(toplam, 1) * 100) if toplam else None

        metrikler.append({
            "tedarikci": t,
            "toplam_lot": toplam,
            "karantina": karantina,
            "iade": iade,
            "puan": round(puan, 1) if puan is not None else None,
        })

    metrikler.sort(key=lambda x: (x["puan"] or 0), reverse=True)

    return templates.TemplateResponse("rapor/tedarikci.html", {
        "request": request, "user": user,
        "metrikler": metrikler,
    })


# ═══ STOK & FİRE RAPORU ══════════════════════════════════

@router.get("/stok", response_class=HTMLResponse)
def stok_raporu(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    now = _now()

    # Aktif stok özeti hammadde bazlı
    hammaddeler = db.query(Hammadde).filter(
        Hammadde.firma_id == fid, Hammadde.aktif == True
    ).all()

    stok_ozet = []
    for h in hammaddeler:
        lotlar = db.query(HammaddeLot).filter(
            HammaddeLot.firma_id == fid,
            HammaddeLot.hammadde_id == h.id,
        ).all()
        kullanilabilir = sum(float(l.kalan_miktar) for l in lotlar if l.durum in (LotDurum.onaylı, LotDurum.kullanımda))
        beklemede = sum(float(l.kalan_miktar) for l in lotlar if l.durum == LotDurum.beklemede)
        karantina = sum(float(l.kalan_miktar) for l in lotlar if l.durum == LotDurum.karantina)
        skt_yaklasan = [l for l in lotlar if l.son_kullanma and (l.son_kullanma - now).days < 30 and l.durum in (LotDurum.onaylı, LotDurum.kullanımda)]

        stok_ozet.append({
            "hammadde": h,
            "kullanilabilir": kullanilabilir,
            "beklemede": beklemede,
            "karantina": karantina,
            "skt_yaklasan": len(skt_yaklasan),
            "kritik_durum": kullanilabilir <= float(h.kritik_stok or 0),
        })

    # Fire özeti
    fire_hareketler = db.query(DepoHareket).filter(
        DepoHareket.firma_id == fid,
        DepoHareket.tip == DepoHareketTip.fire,
    ).order_by(DepoHareket.tarih.desc()).limit(30).all()

    yari_mamul_fire = db.query(YariMamul).filter(
        YariMamul.firma_id == fid,
        YariMamul.durum == YariMamulDurum.fire,
    ).all()

    return templates.TemplateResponse("rapor/stok.html", {
        "request": request, "user": user,
        "stok_ozet": stok_ozet,
        "fire_hareketler": fire_hareketler,
        "yari_mamul_fire": yari_mamul_fire,
        "now": now,
    })


# ═══ DENETİM PAKETİ ══════════════════════════════════════

@router.get("/denetim", response_class=HTMLResponse)
def denetim_paketi(
    request: Request,
    baslangic: Optional[str] = Query(None),
    bitis: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Tarım Bakanlığı denetimi için hazır rapor paketi.
    Tüm modüllerin özeti tek sayfada.
    """
    fid = user.firma_id
    now = _now()
    bas_dt = datetime.strptime(baslangic, "%Y-%m-%d").replace(tzinfo=timezone.utc) if baslangic else now - timedelta(days=90)
    bit_dt = datetime.strptime(bitis, "%Y-%m-%d").replace(tzinfo=timezone.utc) if bitis else now

    # Genel istatistikler
    lot_giris = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == fid,
        HammaddeLot.kabul_tarihi >= bas_dt,
        HammaddeLot.kabul_tarihi <= bit_dt,
    ).count()

    uretim_tamamlanan = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.durum == "tamamlandı",
        UretimEmri.bitis >= bas_dt,
        UretimEmri.bitis <= bit_dt,
    ).count()

    ccp_uyum = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == fid,
        CCPOlcum.olcum_tarihi >= bas_dt,
        CCPOlcum.olcum_tarihi <= bit_dt,
    )
    ccp_toplam = ccp_uyum.count()
    ccp_uygun  = ccp_uyum.filter(CCPOlcum.durum == CCPDurum.uygun).count()

    aktif_recall = db.query(Sikayet).filter(
        Sikayet.firma_id == fid,
        Sikayet.is_recall == True,
        Sikayet.durum != "kapatildi",
    ).all()

    sevkiyat_sayisi = db.query(Sevkiyat).filter(
        Sevkiyat.firma_id == fid,
        Sevkiyat.sevk_tarihi >= bas_dt,
        Sevkiyat.sevk_tarihi <= bit_dt,
    ).count()

    # Son lotlar
    son_lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == fid,
        HammaddeLot.kabul_tarihi >= bas_dt,
    ).order_by(HammaddeLot.kabul_tarihi.desc()).limit(20).all()

    return templates.TemplateResponse("rapor/denetim.html", {
        "request": request, "user": user,
        "baslangic": bas_dt.strftime("%d.%m.%Y"),
        "bitis": bit_dt.strftime("%d.%m.%Y"),
        "baslangic_input": bas_dt.strftime("%Y-%m-%d"),
        "bitis_input": bit_dt.strftime("%Y-%m-%d"),
        "lot_giris": lot_giris,
        "uretim_tamamlanan": uretim_tamamlanan,
        "ccp_toplam": ccp_toplam,
        "ccp_uygun": ccp_uygun,
        "ccp_oran": round(ccp_uygun / ccp_toplam * 100, 1) if ccp_toplam else 0,
        "aktif_recall": aktif_recall,
        "sevkiyat_sayisi": sevkiyat_sayisi,
        "son_lotlar": son_lotlar,
        "now": now,
        "firma": db.query(__import__('app.models.models', fromlist=['Firma']).Firma).filter_by(id=fid).first(),
    })
