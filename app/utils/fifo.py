"""
TraceWay FIFO Motoru
- kabul_tarihi ASC = en eski lot önce
- Sadece onaylı/kullanımda lotlar çekilir
- Her çekim DepoHareket + UretimHammadde kaydı bırakır
"""
from decimal import Decimal
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from app.models.models import (
    HammaddeLot, DepoStok, DepoHareket, DepoHareketTip,
    LotDurum, UretimHammadde
)


def fifo_cek(
    db: Session,
    firma_id: int,
    hammadde_id: int,
    gereken: Decimal,
    depo_id: Optional[int],
    referans_id: Optional[int],
    referans_tip: str,
    yapan_id: Optional[int],
) -> Tuple[bool, List[dict], str]:
    """
    FIFO ile stoktan çeker.
    UretimHammadde tablosuna da yazar — üretim ekranında görünür.
    Returns: (basarili, kullanim_listesi, mesaj)
    """
    q = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id    == firma_id,
        HammaddeLot.hammadde_id == hammadde_id,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda]),
        HammaddeLot.kalan_miktar > 0,
    ).order_by(HammaddeLot.kabul_tarihi.asc())

    if depo_id:
        q = q.filter(HammaddeLot.depo_id == depo_id)

    lotlar = q.all()

    if not lotlar:
        return False, [], "Bu hammadde için onaylı stok bulunamadı."

    kalan = gereken
    liste = []
    fifo_sira = 1

    # Mevcut en yüksek FIFO sırasını bul (aynı emre önceden çekim yapıldıysa)
    if referans_id and referans_tip == "uretim":
        mevcut_max = db.query(UretimHammadde).filter(
            UretimHammadde.emir_id == referans_id
        ).count()
        fifo_sira = mevcut_max + 1

    for lot in lotlar:
        if kalan <= 0:
            break

        mevcut  = Decimal(str(lot.kalan_miktar))
        cekilen = min(mevcut, kalan)
        onceki  = mevcut

        lot.kalan_miktar = mevcut - cekilen
        kalan -= cekilen
        lot.durum = LotDurum.tükendi if lot.kalan_miktar == 0 else LotDurum.kullanımda

        # DepoStok güncelle
        stok = db.query(DepoStok).filter(
            DepoStok.lot_id  == lot.id,
            DepoStok.depo_id == (depo_id or lot.depo_id)
        ).first()
        if stok:
            stok.miktar = lot.kalan_miktar

        # DepoHareket kaydı
        db.add(DepoHareket(
            firma_id       = firma_id,
            depo_id        = lot.depo_id or depo_id,
            lot_id         = lot.id,
            tip            = DepoHareketTip.cikis,
            miktar         = cekilen,
            onceki_miktar  = onceki,
            sonraki_miktar = lot.kalan_miktar,
            aciklama       = f"FIFO çekimi — {referans_tip} #{referans_id}",
            yapan_id       = yapan_id,
        ))

        # UretimHammadde kaydı — üretim ekranında görünsün
        if referans_id and referans_tip == "uretim":
            db.add(UretimHammadde(
                emir_id    = referans_id,
                lot_id     = lot.id,
                fifo_sira  = fifo_sira,
                kullanilan = cekilen,
                yapan_id   = yapan_id,
            ))
            fifo_sira += 1

        liste.append({
            "lot_id":     lot.id,
            "lot_no":     lot.lot_no,
            "ic_parti":   lot.ic_parti_no,
            "kullanilan": float(cekilen),
        })

    if kalan > 0:
        db.rollback()
        return False, [], f"Yetersiz stok! {float(kalan):.2f} {'' } eksik."

    db.commit()
    return True, liste, "OK"


def lot_giris_kaydet(db: Session, lot: HammaddeLot, yapan_id: Optional[int]):
    """Yeni lot girişinde DepoStok + DepoHareket oluşturur."""
    stok = db.query(DepoStok).filter(
        DepoStok.lot_id  == lot.id,
        DepoStok.depo_id == lot.depo_id
    ).first()
    if stok:
        stok.miktar += lot.giris_miktar
    else:
        db.add(DepoStok(
            firma_id = lot.firma_id,
            depo_id  = lot.depo_id,
            lot_id   = lot.id,
            miktar   = lot.giris_miktar,
        ))
    db.add(DepoHareket(
        firma_id       = lot.firma_id,
        depo_id        = lot.depo_id,
        lot_id         = lot.id,
        tip            = DepoHareketTip.giris,
        miktar         = lot.giris_miktar,
        onceki_miktar  = 0,
        sonraki_miktar = lot.giris_miktar,
        aciklama       = f"Hammadde girişi — {lot.lot_no}",
        yapan_id       = yapan_id,
    ))
    db.flush()


def toplam_stok(db: Session, firma_id: int, hammadde_id: int) -> Decimal:
    from sqlalchemy import func
    r = db.query(func.sum(HammaddeLot.kalan_miktar)).filter(
        HammaddeLot.firma_id    == firma_id,
        HammaddeLot.hammadde_id == hammadde_id,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda]),
    ).scalar()
    return Decimal(str(r or 0))


def fifo_sirala(db: Session, firma_id: int, hammadde_id: int):
    """Aktif lotlara FIFO sıra numarası atar."""
    lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id    == firma_id,
        HammaddeLot.hammadde_id == hammadde_id,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda, LotDurum.beklemede]),
    ).order_by(HammaddeLot.kabul_tarihi.asc()).all()
    for i, lot in enumerate(lotlar, 1):
        lot.fifo_sira = i
    db.flush()
