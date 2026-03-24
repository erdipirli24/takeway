"""
Bildirim Servisi
================
Sistem olaylarını dinler ve BildirimKaydi oluşturur.
Her request sonrası veya zamanlanmış görev olarak çalışır.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.models import (
    HammaddeLot, Hammadde, Numune, CCPOlcum, Sikayet,
    BildirimKaydi, LotDurum, NumuneDurum, CCPDurum,
    SikayetDurum, SikayetOncelik
)
from sqlalchemy import func


def bildirim_olustur(
    db: Session,
    firma_id: int,
    tip: str,
    baslik: str,
    mesaj: str = "",
    kullanici_id: int = None,
    ilgili_tip: str = None,
    ilgili_id: int = None,
):
    """Tekrar eden bildirimi önle — son 24 saatte aynı bildirimleri atla."""
    son_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    mevcut = db.query(BildirimKaydi).filter(
        BildirimKaydi.firma_id == firma_id,
        BildirimKaydi.tip == tip,
        BildirimKaydi.ilgili_id == ilgili_id,
        BildirimKaydi.created_at >= son_24h,
    ).first()
    if mevcut:
        return  # zaten var

    db.add(BildirimKaydi(
        firma_id    = firma_id,
        kullanici_id = kullanici_id,
        tip         = tip,
        baslik      = baslik,
        mesaj       = mesaj,
        ilgili_tip  = ilgili_tip,
        ilgili_id   = ilgili_id,
    ))


def tum_kontrolleri_calistir(db: Session, firma_id: int):
    """Tüm alarm kontrollerini çalıştırır."""
    now = datetime.now(timezone.utc)

    # 1. SKT uyarıları (7 gün içinde)
    skt_lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == firma_id,
        HammaddeLot.son_kullanma <= now + timedelta(days=7),
        HammaddeLot.son_kullanma >= now,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda, LotDurum.beklemede])
    ).all()
    for lot in skt_lotlar:
        kalan = (lot.son_kullanma - now).days
        bildirim_olustur(
            db, firma_id, "skt_uyari",
            f"SKT Uyarısı: {lot.hammadde.ad}",
            f"{lot.ic_parti_no or lot.lot_no} — {kalan} gün kaldı",
            ilgili_tip="lot", ilgili_id=lot.id
        )

    # 2. Kritik stok seviyesi
    hammaddeler = db.query(Hammadde).filter(
        Hammadde.firma_id == firma_id, Hammadde.aktif == True
    ).all()
    for h in hammaddeler:
        if not h.kritik_stok:
            continue
        toplam = db.query(func.sum(HammaddeLot.kalan_miktar)).filter(
            HammaddeLot.firma_id == firma_id,
            HammaddeLot.hammadde_id == h.id,
            HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda])
        ).scalar() or 0
        if float(toplam) <= float(h.kritik_stok):
            bildirim_olustur(
                db, firma_id, "kritik_stok",
                f"Kritik Stok: {h.ad}",
                f"Mevcut: {toplam:.2f} {h.birim} (kritik eşik: {h.kritik_stok})",
                ilgili_tip="hammadde", ilgili_id=h.id
            )

    # 3. Bekleyen numuneler (48 saatten uzun)
    eski_numune = db.query(Numune).filter(
        Numune.firma_id == firma_id,
        Numune.durum == NumuneDurum.beklemede,
        Numune.alinma_tarihi <= now - timedelta(hours=48)
    ).all()
    for n in eski_numune:
        bildirim_olustur(
            db, firma_id, "numune_bekliyor",
            f"Numune Bekliyor: {n.numune_no}",
            f"48 saatır onay bekleniyor",
            ilgili_tip="numune", ilgili_id=n.id
        )

    # 4. CCP kritik sapma (düzeltici yapılmamış)
    ccp_sapma = db.query(CCPOlcum).filter(
        CCPOlcum.firma_id == firma_id,
        CCPOlcum.durum == CCPDurum.kritik,
        CCPOlcum.duzeltici_yapildi == False,
        CCPOlcum.olcum_tarihi >= now - timedelta(hours=24)
    ).all()
    for c in ccp_sapma:
        bildirim_olustur(
            db, firma_id, "ccp_kritik",
            f"CCP Kritik Sapma: {c.ccp_tanim.ad if c.ccp_tanim else ''}",
            f"Ölçülen: {c.olculen_deger} — Düzeltici eylem bekleniyor",
            ilgili_tip="ccp", ilgili_id=c.id
        )

    # 5. Aktif recall
    recall = db.query(Sikayet).filter(
        Sikayet.firma_id == firma_id,
        Sikayet.is_recall == True,
        Sikayet.durum == SikayetDurum.recall
    ).all()
    for s in recall:
        bildirim_olustur(
            db, firma_id, "recall_aktif",
            f"AKTİF RECALL: {s.sikayet_no}",
            s.baslik,
            ilgili_tip="sikayet", ilgili_id=s.id
        )

    db.commit()


def okunmamis_sayisi(db: Session, firma_id: int) -> int:
    return db.query(BildirimKaydi).filter(
        BildirimKaydi.firma_id == firma_id,
        BildirimKaydi.okundu == False,
    ).count()
