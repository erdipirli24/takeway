from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, UretimEmri, UretimAsama, UretimHammadde, UretimMakineAtama,
    UrunParti, YariMamul, YariMamulKullanim, YariMamulDurum,
    Recete, ReceteKalem, ReceteTip, Urun, Makine, MacineDurum,
    HammaddeLot, Hammadde, Depo, LotDurum, UretimDurum,
    KaliteKontrol, DepoHareket, DepoHareketTip
)
from app.utils.fifo import fifo_cek, toplam_stok
from app.utils.helpers import qr_olustur

router = APIRouter(prefix="/uretim", tags=["uretim"])

VARSAYILAN_ASAMALAR = [
    "Hammadde Kabulü & Tartım",
    "Ön Hazırlık",
    "Karışım / Yoğurma",
    "Dinlendirme / Bekleme",
    "Şekillendirme",
    "Pişirme / İşleme",
    "Soğutma",
    "Paketleme & Etiketleme",
    "Kalite Kontrol",
    "Sevkiyata Hazırlık",
]


def _emri_no(db: Session, firma_id: int) -> str:
    from datetime import datetime
    sira = db.query(UretimEmri).filter(UretimEmri.firma_id == firma_id).count() + 1
    return f"UE-{firma_id:02d}-{datetime.now().strftime('%y%m%d')}-{sira:04d}"


def _parti_no(db: Session, firma_id: int, urun_id: int) -> str:
    sira = db.query(UrunParti).filter(UrunParti.firma_id == firma_id).count() + 1
    return f"UP-{firma_id:02d}-U{urun_id:03d}-{datetime.now().strftime('%y%m%d')}-{sira:04d}"


def _yari_parti_no(db: Session, firma_id: int) -> str:
    sira = db.query(YariMamul).filter(YariMamul.firma_id == firma_id).count() + 1
    return f"YM-{firma_id:02d}-{datetime.now().strftime('%y%m%d')}-{sira:04d}"


def _now():
    return datetime.now(timezone.utc)


# ═══ EMİR LİSTESİ ════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
def emir_listesi(
    request: Request,
    durum: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(UretimEmri).filter(UretimEmri.firma_id == user.firma_id)
    if durum: query = query.filter(UretimEmri.durum == durum)
    if q: query = query.filter(
        (UretimEmri.urun_adi.ilike(f"%{q}%")) | (UretimEmri.emri_no.ilike(f"%{q}%"))
    )
    emirler = query.order_by(UretimEmri.created_at.desc()).all()

    receteler = db.query(Recete).filter(
        Recete.firma_id == user.firma_id,
        Recete.onaylandi == True,
        Recete.aktif == True
    ).all()
    urunler = db.query(Urun).filter(Urun.firma_id == user.firma_id, Urun.aktif == True).all()
    birimler_ozel = ["kg","g","lt","ml","adet","tepsi","dilim","porsiyon","paket"]

    return templates.TemplateResponse("uretim/liste.html", {
        "request": request, "user": user,
        "emirler": emirler,
        "receteler": receteler,
        "urunler": urunler,
        "birimler": birimler_ozel,
        "UretimDurum": UretimDurum,
        "filtre_durum": durum, "q": q or "",
    })


# ═══ YENİ EMİR ═══════════════════════════════════════════

@router.post("/ekle")
def emir_ekle(
    recete_id: Optional[int] = Form(None),
    urun_id: Optional[int] = Form(None),
    urun_adi: str = Form(""),
    hedef_miktar: float = Form(...),
    hedef_birim: str = Form("kg"),
    baslangic: Optional[str] = Form(None),
    oncelik: int = Form(2),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id

    def parse_dt(s):
        if s:
            try: return datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            except:
                try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except: pass
        return None

    # Ürün adı
    if urun_id and not urun_adi:
        u = db.query(Urun).filter(Urun.id == urun_id).first()
        if u: urun_adi = u.ad

    no = _emri_no(db, fid)
    qr = qr_olustur(f"TW-EMİR\nNo: {no}\nÜrün: {urun_adi}\n{hedef_miktar} {hedef_birim}")

    emir = UretimEmri(
        firma_id       = fid,
        recete_id      = recete_id or None,
        urun_id        = urun_id or None,
        emri_no        = no,
        urun_adi       = urun_adi,
        hedef_miktar   = hedef_miktar,
        hedef_birim    = hedef_birim,
        durum          = UretimDurum.planlandı,
        oncelik        = oncelik,
        baslangic      = parse_dt(baslangic),
        notlar         = notlar or None,
        qr_data        = qr,
        created_by     = user.id,
    )
    db.add(emir); db.flush()

    # Varsayılan aşamalar
    for i, asama_adi in enumerate(VARSAYILAN_ASAMALAR, 1):
        db.add(UretimAsama(emir_id=emir.id, sira=i, ad=asama_adi))

    db.commit()
    return RedirectResponse(f"/uretim/{emir.id}", status_code=302)


# ═══ EMİR DETAY ══════════════════════════════════════════

@router.get("/{eid}", response_class=HTMLResponse)
def emir_detay(
    eid: int, request: Request,
    hata: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    emir = db.query(UretimEmri).filter(UretimEmri.id == eid, UretimEmri.firma_id == user.firma_id).first()
    if not emir:
        return RedirectResponse("/uretim/", status_code=302)

    # Reçete varsa hammadde listesi
    recete_kalemleri = []
    if emir.recete_id:
        recete_kalemleri = db.query(ReceteKalem).filter(
            ReceteKalem.recete_id == emir.recete_id
        ).order_by(ReceteKalem.sira).all()

    # Kullanılabilir hammadde lotları
    aktif_lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == user.firma_id,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda]),
        HammaddeLot.kalan_miktar > 0,
    ).order_by(HammaddeLot.hammadde_id, HammaddeLot.kabul_tarihi.asc()).all()

    # Kullanılabilir yarı mamuller
    yari_mamuller = db.query(YariMamul).filter(
        YariMamul.firma_id == user.firma_id,
        YariMamul.durum == YariMamulDurum.stokta,
        YariMamul.kalan_miktar > 0,
    ).all()

    # Makineler
    makineler = db.query(Makine).filter(Makine.firma_id == user.firma_id).order_by(Makine.tip, Makine.ad).all()

    # Atanmış makineler
    atanan_makineler = db.query(UretimMakineAtama).filter(
        UretimMakineAtama.emir_id == eid
    ).all()

    hammaddeler = db.query(Hammadde).filter(Hammadde.firma_id == user.firma_id, Hammadde.aktif == True).all()
    depolar     = db.query(Depo).filter(Depo.firma_id == user.firma_id, Depo.aktif == True).all()
    urunler     = db.query(Urun).filter(Urun.firma_id == user.firma_id, Urun.aktif == True).all()

    return templates.TemplateResponse("uretim/detay.html", {
        "request": request, "user": user,
        "emir": emir,
        "recete_kalemleri": recete_kalemleri,
        "aktif_lotlar": aktif_lotlar,
        "yari_mamuller": yari_mamuller,
        "makineler": makineler,
        "atanan_makineler": atanan_makineler,
        "hammaddeler": hammaddeler,
        "depolar": depolar,
        "urunler": urunler,
        "UretimDurum": UretimDurum,
        "MacineDurum": MacineDurum,
        "hata": hata,
        "now": _now(),
    })


# ═══ DURUM GÜNCELLE ══════════════════════════════════════

@router.post("/{eid}/durum")
def emir_durum(
    eid: int,
    durum: str = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    emir = db.query(UretimEmri).filter(UretimEmri.id == eid, UretimEmri.firma_id == user.firma_id).first()
    if emir:
        emir.durum = durum
        if durum == UretimDurum.devam and not emir.baslangic:
            emir.baslangic = _now()
        if durum == UretimDurum.tamamlandı:
            emir.bitis = _now()
        db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ MAKİNE ATA ═══════════════════════════════════════════

@router.post("/{eid}/makine-ata")
def makine_ata(
    eid: int,
    makine_id: int = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Aynı makine zaten atanmış mı?
    mevcut = db.query(UretimMakineAtama).filter(
        UretimMakineAtama.emir_id == eid,
        UretimMakineAtama.makine_id == makine_id
    ).first()
    if not mevcut:
        db.add(UretimMakineAtama(
            emir_id=eid, makine_id=makine_id,
            baslangic=_now()
        ))
        db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


@router.post("/{eid}/makine-kaldir/{atama_id}")
def makine_kaldir(
    eid: int, atama_id: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(UretimMakineAtama).filter(UretimMakineAtama.id == atama_id).delete()
    db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ FIFO HAMMADDe ÇEK ═══════════════════════════════════

@router.post("/{eid}/fifo-cek")
def fifo_hammadde(
    eid: int,
    hammadde_id: int = Form(...),
    miktar: float = Form(...),
    depo_id: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # depo_id boş string gelebilir — güvenli parse
    _depo_id = int(depo_id) if depo_id and depo_id.strip().isdigit() else None

    ok, _, mesaj = fifo_cek(
        db=db,
        firma_id       = user.firma_id,
        hammadde_id    = hammadde_id,
        gereken        = Decimal(str(miktar)),
        depo_id        = _depo_id,
        referans_id    = eid,
        referans_tip   = "uretim",
        yapan_id       = user.id,
    )
    if not ok:
        return RedirectResponse(f"/uretim/{eid}?hata={mesaj}", status_code=302)
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


@router.post("/{eid}/fifo-oto")
def fifo_oto(
    eid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Otomatik FIFO: Reçetedeki TÜM hammaddeleri üretim miktarına göre
    otomatik olarak çeker. Depo seçmeye gerek yok.
    """
    emir = db.query(UretimEmri).filter(
        UretimEmri.id == eid,
        UretimEmri.firma_id == user.firma_id
    ).first()
    if not emir or not emir.recete_id:
        return RedirectResponse(f"/uretim/{eid}?hata=Reçete bağlı değil. Önce reçete seçin.", status_code=302)

    from app.models.models import ReceteKalem
    kalemler = db.query(ReceteKalem).filter(
        ReceteKalem.recete_id == emir.recete_id,
        ReceteKalem.hammadde_id != None,
    ).all()

    if not kalemler:
        return RedirectResponse(f"/uretim/{eid}?hata=Reçetede hammadde kalemi yok.", status_code=302)

    hatalar = []
    for k in kalemler:
        # Reçete baz miktarına göre ölçekle
        gereken = Decimal(str(k.miktar)) * Decimal(str(emir.hedef_miktar))

        ok, _, mesaj = fifo_cek(
            db=db,
            firma_id     = user.firma_id,
            hammadde_id  = k.hammadde_id,
            gereken      = gereken,
            depo_id      = None,
            referans_id  = eid,
            referans_tip = "uretim",
            yapan_id     = user.id,
        )
        if not ok:
            hatalar.append(f"{k.hammadde.ad if k.hammadde else k.hammadde_id}: {mesaj}")

    if hatalar:
        hata_str = " | ".join(hatalar)
        return RedirectResponse(f"/uretim/{eid}?hata={hata_str}", status_code=302)

    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ YARI MAMUL KULLAN ═══════════════════════════════════

@router.post("/{eid}/yari-mamul-kullan")
def yari_mamul_kullan(
    eid: int,
    yari_mamul_id: int = Form(...),
    kullanilan: float = Form(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    ym = db.query(YariMamul).filter(
        YariMamul.id == yari_mamul_id,
        YariMamul.firma_id == user.firma_id
    ).first()
    if ym and float(ym.kalan_miktar) >= kullanilan:
        ym.kalan_miktar = float(ym.kalan_miktar) - kullanilan
        if ym.kalan_miktar <= 0:
            ym.durum = YariMamulDurum.tukendi
        else:
            ym.durum = YariMamulDurum.kullanımda
        db.add(YariMamulKullanim(
            yari_mamul_id  = yari_mamul_id,
            uretim_emri_id = eid,
            kullanilan     = kullanilan,
            yapan_id       = user.id,
        ))
        db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ AŞAMA TAMAMLA ═══════════════════════════════════════

@router.post("/{eid}/asama/{aid}/tamamla")
def asama_tamamla(
    eid: int, aid: int,
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    a = db.query(UretimAsama).filter(UretimAsama.id == aid, UretimAsama.emir_id == eid).first()
    if a:
        a.tamamlandi = True
        a.bitis      = _now()
        a.notlar     = notlar or None
        db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ KALİTE KONTROL ══════════════════════════════════════

@router.post("/{eid}/asama/{aid}/kontrol")
def kontrol_ekle(
    eid: int, aid: int,
    parametre: str = Form(...),
    hedef_deger: str = Form(""),
    olculen: str = Form(""),
    birim: str = Form(""),
    gecti_mi: Optional[str] = Form(None),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    gecti = None
    if gecti_mi == "1": gecti = True
    elif gecti_mi == "0": gecti = False

    db.add(KaliteKontrol(
        asama_id    = aid,
        parametre   = parametre,
        hedef_deger = hedef_deger or None,
        olculen     = olculen or None,
        birim       = birim or None,
        gecti_mi    = gecti,
        notlar      = notlar or None,
        yapan_id    = user.id,
    ))
    db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ YARI MAMUL ÜRETİM (KARIşIM MODU) ═══════════════════

@router.post("/{eid}/yari-uret")
def yari_uret(
    eid: int,
    recete_id: int = Form(...),
    ad: str = Form(...),
    miktar: float = Form(...),
    birim: str = Form("kg"),
    raf_omru_gun: int = Form(...),
    depo_id: Optional[int] = Form(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    parti_no = _yari_parti_no(db, fid)
    son_kullanma = _now() + timedelta(days=raf_omru_gun)

    qr = qr_olustur(
        f"TW-YARI MAMUL\n"
        f"Parti: {parti_no}\n"
        f"Ad: {ad}\n"
        f"Miktar: {miktar} {birim}\n"
        f"RAF ÖMRÜ: {raf_omru_gun} gün\n"
        f"SKT: {son_kullanma.strftime('%d.%m.%Y %H:%M')}"
    )

    ym = YariMamul(
        firma_id       = fid,
        recete_id      = recete_id,
        uretim_emri_id = eid,
        parti_no       = parti_no,
        ad             = ad,
        uretim_miktari = miktar,
        kalan_miktar   = miktar,
        birim          = birim,
        raf_omru_gun   = raf_omru_gun,
        son_kullanma   = son_kullanma,
        depo_id        = depo_id or None,
        qr_data        = qr,
        created_by     = user.id,
    )
    db.add(ym); db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ NİHAİ ÜRÜN PARTİSİ ══════════════════════════════════

@router.post("/{eid}/parti-kaydet")
def parti_kaydet(
    eid: int,
    urun_id: int = Form(...),
    parti_no_giris: Optional[str] = Form(None),
    miktar: float = Form(...),
    birim: str = Form("kg"),
    uretim_tarihi: Optional[str] = Form(None),
    son_kullanma: Optional[str] = Form(None),
    depo_id: Optional[int] = Form(None),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id

    def parse_dt(s):
        if s:
            try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except: pass
        return None

    pno = parti_no_giris.strip() if parti_no_giris and parti_no_giris.strip() else _parti_no(db, fid, urun_id)

    qr = qr_olustur(
        f"TW-PARTİ\n"
        f"Parti No: {pno}\n"
        f"Üretim Emri: {eid}\n"
        f"Miktar: {miktar} {birim}\n"
        f"Tarih: {uretim_tarihi or ''}"
    )

    p = UrunParti(
        firma_id       = fid,
        urun_id        = urun_id,
        uretim_emri_id = eid,
        parti_no       = pno,
        uretim_miktari = miktar,
        kalan_miktar   = miktar,
        birim          = birim,
        uretim_tarihi  = parse_dt(uretim_tarihi),
        son_kullanma   = parse_dt(son_kullanma),
        depo_id        = depo_id or None,
        qr_data        = qr,
        notlar         = notlar or None,
    )
    db.add(p)

    # Üretilen miktarı güncelle
    emir = db.query(UretimEmri).filter(UretimEmri.id == eid).first()
    if emir:
        emir.uretilen_miktar = float(emir.uretilen_miktar or 0) + miktar

    db.commit()
    return RedirectResponse(f"/uretim/{eid}", status_code=302)


# ═══ PARTİ DETAY — İZLENEBİLİRLİK ═══════════════════════

@router.get("/parti/{pid}", response_class=HTMLResponse)
def parti_detay(
    pid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    parti = db.query(UrunParti).filter(UrunParti.id == pid, UrunParti.firma_id == user.firma_id).first()
    if not parti:
        return RedirectResponse("/uretim/", status_code=302)

    emir      = parti.uretim_emri
    kullanim  = db.query(UretimHammadde).filter(
        UretimHammadde.emir_id == emir.id
    ).order_by(UretimHammadde.fifo_sira).all()

    ym_kullanim = db.query(YariMamulKullanim).filter(
        YariMamulKullanim.uretim_emri_id == emir.id
    ).all()

    makineler = db.query(UretimMakineAtama).filter(
        UretimMakineAtama.emir_id == emir.id
    ).all()

    return templates.TemplateResponse("uretim/parti_detay.html", {
        "request": request, "user": user,
        "parti": parti,
        "emir": emir,
        "kullanim": kullanim,
        "ym_kullanim": ym_kullanim,
        "makineler": makineler,
    })


# ═══ YARI MAMUL RAF ÖMRÜ KONTROL (zamanlanmış görev) ════

@router.get("/yari-mamul/kontrol", response_class=HTMLResponse)
def yari_mamul_listesi(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Yarı mamulleri listele, süresi dolmuşları otomatik fire et."""
    now = _now()
    fid = user.firma_id

    # Süresi dolmuş → fire
    dolmus = db.query(YariMamul).filter(
        YariMamul.firma_id == fid,
        YariMamul.durum == YariMamulDurum.stokta,
        YariMamul.son_kullanma < now,
        YariMamul.kalan_miktar > 0,
    ).all()
    for ym in dolmus:
        ym.durum        = YariMamulDurum.fire
        ym.kalan_miktar = 0

    if dolmus:
        db.commit()

    yari_mamuller = db.query(YariMamul).filter(
        YariMamul.firma_id == fid
    ).order_by(YariMamul.uretim_tarihi.desc()).all()

    return templates.TemplateResponse("uretim/yari_mamul.html", {
        "request": request, "user": user,
        "yari_mamuller": yari_mamuller,
        "fire_sayisi": len(dolmus),
        "now": now,
        "YariMamulDurum": YariMamulDurum,
    })
