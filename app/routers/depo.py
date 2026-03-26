from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

from app.database import get_db
from app.auth import get_current_user, yetki_kontrol
from app.models.models import (
    Kullanici, Firma, Depo, DepoStok, DepoHareket, DepoHareketTip,
    HammaddeLot, Hammadde, HammaddeKategori, Tedarikci,
    Numune, NumuneTip, NumuneDurum, NumuneLab, LotDurum,
    ALERJEN_LISTESI
)
from app.utils.fifo import lot_giris_kaydet, fifo_sirala, toplam_stok
from app.utils.helpers import qr_olustur, ic_parti_no, numune_no

router = APIRouter(prefix="/depo", tags=["depo"])


def _parse_dt(s):
    if s:
        try: return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except: pass
    return None


# ═══ DEPO TANIMLAR ═══════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
def depo_listesi(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    depolar = db.query(Depo).filter(Depo.firma_id == user.firma_id, Depo.aktif == True).all()
    return templates.TemplateResponse("depo/liste.html", {
        "request": request, "user": user, "depolar": depolar
    })


@router.post("/tanimla")
def depo_tanimla(
    ad: str = Form(...), kod: str = Form(""), tip: str = Form("hammadde"),
    adres: str = Form(""), min_sicaklik: str = Form(""),
    max_sicaklik: str = Form(""), notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.add(Depo(
        firma_id     = user.firma_id,
        ad           = ad,
        kod          = kod or None,
        tip          = tip,
        adres        = adres or None,
        min_sicaklik = safe_float(min_sicaklik),
        max_sicaklik = safe_float(max_sicaklik),
        notlar       = notlar or None,
        aktif        = True,
    ))
    db.commit()
    return RedirectResponse("/depo/", status_code=302)


@router.post("/sil/{did}")
def depo_sil(
    did: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sadece firma admin silebilir."""
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/depo/", status_code=302)
    depo = db.query(Depo).filter(Depo.id == did, Depo.firma_id == user.firma_id).first()
    if depo:
        depo.aktif = False
        db.commit()
    return RedirectResponse("/depo/", status_code=302)


# ═══ HAMMADDE TANIMLAR ═══════════════════════════════════

@router.get("/hammadde", response_class=HTMLResponse)
def hammadde_listesi(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    hammaddeler = db.query(Hammadde).filter(Hammadde.firma_id == user.firma_id, Hammadde.aktif == True).order_by(Hammadde.ad).all()
    kategoriler = db.query(HammaddeKategori).filter(HammaddeKategori.firma_id == user.firma_id).all()
    stoklar     = {h.id: float(toplam_stok(db, user.firma_id, h.id)) for h in hammaddeler}
    return templates.TemplateResponse("hammadde/liste.html", {
        "request": request, "user": user,
        "hammaddeler": hammaddeler, "kategoriler": kategoriler,
        "stoklar": stoklar, "ALERJEN_LISTESI": ALERJEN_LISTESI,
    })


@router.post("/hammadde/ekle")
async def hammadde_ekle(
    request: Request,
    ad: str = Form(...), kod: str = Form(""), birim: str = Form("kg"),
    kategori_id: str = Form(""),
    min_stok: float = Form(0), kritik_stok: float = Form(0),
    aciklama: str = Form(""), numune_gerekli: Optional[str] = Form(None),
    user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)
):
    form = await request.form()
    # Allerjenler: form'da alerjen_gluten, alerjen_sut gibi checkbox'lar
    secili = [a for a in ALERJEN_LISTESI if f"alerjen_{a}" in form]
    db.add(Hammadde(
        firma_id=user.firma_id, ad=ad, kod=kod or None, birim=birim,
        kategori_id=safe_int(kategori_id), min_stok=min_stok, kritik_stok=kritik_stok,
        aciklama=aciklama or None, alerjenler=",".join(secili),
        numune_gerekli=(numune_gerekli == "on"),
    ))
    db.commit()
    return RedirectResponse("/depo/hammadde", status_code=302)


@router.get("/tedarikci", response_class=HTMLResponse)
def tedarikci_listesi(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    t_list = db.query(Tedarikci).filter(Tedarikci.firma_id == user.firma_id).order_by(Tedarikci.ad).all()
    return templates.TemplateResponse("depo/tedarikci.html", {
        "request": request, "user": user, "tedarikciler": t_list
    })


@router.post("/tedarikci/ekle")
def tedarikci_ekle(
    ad: str = Form(...), kod: str = Form(""), vergi_no: str = Form(""),
    email: str = Form(""), telefon: str = Form(""), adres: str = Form(""),
    user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.add(Tedarikci(firma_id=user.firma_id, ad=ad, kod=kod or None,
                     vergi_no=vergi_no or None, email=email or None,
                     telefon=telefon or None, adres=adres or None))
    db.commit()
    return RedirectResponse("/depo/tedarikci", status_code=302)


# ═══ HAMMADDe GİRİŞ ══════════════════════════════════════

@router.get("/giris", response_class=HTMLResponse)
def giris_formu(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse("depo/giris.html", {
        "request": request, "user": user,
        "hammaddeler": db.query(Hammadde).filter(Hammadde.firma_id == user.firma_id, Hammadde.aktif == True).order_by(Hammadde.ad).all(),
        "tedarikciler": db.query(Tedarikci).filter(Tedarikci.firma_id == user.firma_id, Tedarikci.aktif == True).order_by(Tedarikci.ad).all(),
        "depolar": db.query(Depo).filter(Depo.firma_id == user.firma_id, Depo.aktif == True).all(),
        "bugun": datetime.now().strftime("%Y-%m-%d"),
    })


@router.post("/giris")
def giris_kaydet(
    hammadde_id: int = Form(...),
    depo_id: int = Form(...),
    tedarikci_id: int = Form(...),
    fatura_no: str = Form(...),
    fatura_tarihi: str = Form(...),
    lot_no: str = Form(...),
    ic_parti: Optional[str] = Form(None),
    miktar: float = Form(...),
    birim_fiyat: str = Form(""),
    para_birimi: str = Form("TRY"),
    uretim_tarihi: Optional[str] = Form(None),
    son_kullanma: Optional[str] = Form(None),
    depo_konumu: str = Form(""),
    sertifika_no: str = Form(""),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    hm  = db.query(Hammadde).filter(Hammadde.id == hammadde_id, Hammadde.firma_id == fid).first()
    if not hm:
        return RedirectResponse("/depo/giris", status_code=302)

    # İç parti no otomatik
    if not ic_parti or not ic_parti.strip():
        sira = db.query(HammaddeLot).filter(HammaddeLot.firma_id == fid).count() + 1
        ic_parti = ic_parti_no(fid, hammadde_id, sira)

    # QR içeriği
    qr_text = (
        f"TRACEWAY LOT\n"
        f"İç Parti : {ic_parti}\n"
        f"Hammadde : {hm.ad}\n"
        f"Tedarikçi Lot: {lot_no}\n"
        f"Fatura No: {fatura_no}\n"
        f"Miktar   : {miktar} {hm.birim}\n"
        f"SKT      : {son_kullanma or '—'}"
    )

    # Numune gerekiyorsa beklemede başlar
    baslangic_durum = LotDurum.beklemede if hm.numune_gerekli else LotDurum.onaylı

    lot = HammaddeLot(
        firma_id     = fid,
        hammadde_id  = hammadde_id,
        tedarikci_id = tedarikci_id,
        depo_id      = depo_id,
        lot_no       = lot_no,
        ic_parti_no  = ic_parti,
        fatura_no    = fatura_no,
        fatura_tarihi = _parse_dt(fatura_tarihi),
        giris_miktar = miktar,
        kalan_miktar = miktar,
        birim        = hm.birim,
        birim_fiyat  = safe_float(birim_fiyat),
        para_birimi  = para_birimi,
        durum        = baslangic_durum,
        uretim_tarihi = _parse_dt(uretim_tarihi),
        son_kullanma  = _parse_dt(son_kullanma),
        kabul_tarihi  = datetime.now(timezone.utc),
        depo_konumu  = depo_konumu or None,
        sertifika_no = sertifika_no or None,
        notlar       = notlar or None,
        qr_data      = qr_olustur(qr_text),
        created_by   = user.id,
    )
    db.add(lot); db.flush()
    lot_giris_kaydet(db, lot, user.id)

    # Tedarikçi sayacı güncelle
    t = db.query(Tedarikci).filter(Tedarikci.id == tedarikci_id).first()
    if t: t.toplam_lot += 1

    # Numune gerekiyorsa otomatik numune kaydı aç
    if hm.numune_gerekli:
        sira_n = db.query(Numune).filter(Numune.firma_id == fid).count() + 1
        nm = Numune(
            firma_id     = fid,
            lot_id       = lot.id,
            tip          = NumuneTip.hammadde,
            lab_tipi     = NumuneLab.dahili,
            durum        = NumuneDurum.beklemede,
            numune_no    = numune_no(fid, sira_n),
            miktar       = 250,
            birim        = "g",
            alinma_tarihi = datetime.now(timezone.utc),
            alan_id      = user.id,
            qr_data      = qr_olustur(
                f"NUMUNE\n{numune_no(fid, sira_n)}\n{hm.ad}\nLot: {ic_parti}\nTarih: {datetime.now().strftime('%d.%m.%Y')}"
            ),
        )
        db.add(nm)

    fifo_sirala(db, fid, hammadde_id)
    db.commit()
    return RedirectResponse(f"/depo/lot/{lot.id}", status_code=302)


# ═══ STOK GÖRÜNÜMÜ ═══════════════════════════════════════

@router.get("/stok", response_class=HTMLResponse)
def stok(
    request: Request,
    hammadde_id: Optional[int] = Query(None),
    depo_id: Optional[int] = Query(None),
    durum: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    query = db.query(HammaddeLot).filter(HammaddeLot.firma_id == fid)
    if hammadde_id: query = query.filter(HammaddeLot.hammadde_id == hammadde_id)
    if depo_id:     query = query.filter(HammaddeLot.depo_id == depo_id)
    if durum:       query = query.filter(HammaddeLot.durum == durum)
    if q:           query = query.filter(
        (HammaddeLot.lot_no.ilike(f"%{q}%")) | (HammaddeLot.ic_parti_no.ilike(f"%{q}%"))
    )
    lotlar = query.order_by(HammaddeLot.hammadde_id, HammaddeLot.kabul_tarihi.asc()).all()

    return templates.TemplateResponse("depo/stok.html", {
        "request": request, "user": user,
        "lotlar": lotlar, "LotDurum": LotDurum,
        "hammaddeler": db.query(Hammadde).filter(Hammadde.firma_id == fid).all(),
        "depolar": db.query(Depo).filter(Depo.firma_id == fid).all(),
        "filtre_hm": hammadde_id, "filtre_depo": depo_id,
        "filtre_durum": durum, "q": q or "",
        "now": datetime.now(timezone.utc),
    })


# ═══ LOT DETAY ═══════════════════════════════════════════

@router.get("/lot/{lid}", response_class=HTMLResponse)
def lot_detay(lid: int, request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    lot = db.query(HammaddeLot).filter(HammaddeLot.id == lid, HammaddeLot.firma_id == user.firma_id).first()
    if not lot: return RedirectResponse("/depo/stok", status_code=302)

    hareketler = db.query(DepoHareket).filter(DepoHareket.lot_id == lid).order_by(DepoHareket.tarih.desc()).all()
    numuneler  = db.query(Numune).filter(Numune.lot_id == lid).all()

    fifo_lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id    == user.firma_id,
        HammaddeLot.hammadde_id == lot.hammadde_id,
        HammaddeLot.durum.in_([LotDurum.onaylı, LotDurum.kullanımda, LotDurum.beklemede])
    ).order_by(HammaddeLot.kabul_tarihi.asc()).all()
    fifo_konum = next((i+1 for i, l in enumerate(fifo_lotlar) if l.id == lid), None)

    return templates.TemplateResponse("depo/lot_detay.html", {
        "request": request, "user": user, "lot": lot,
        "hareketler": hareketler, "numuneler": numuneler,
        "fifo_konum": fifo_konum, "fifo_toplam": len(fifo_lotlar),
        "LotDurum": LotDurum, "now": datetime.now(timezone.utc),
    })


@router.post("/lot/{lid}/durum")
def lot_durum(
    lid: int, durum: str = Form(...), kalite_notu: str = Form(""),
    user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)
):
    lot = db.query(HammaddeLot).filter(HammaddeLot.id == lid, HammaddeLot.firma_id == user.firma_id).first()
    if lot:
        lot.durum = durum
        if kalite_notu: lot.kalite_notu = kalite_notu
        if durum == LotDurum.karantina:
            t = db.query(Tedarikci).filter(Tedarikci.id == lot.tedarikci_id).first()
            if t: t.karantina_lot += 1
        fifo_sirala(db, user.firma_id, lot.hammadde_id)
        db.commit()
    return RedirectResponse(f"/depo/lot/{lid}", status_code=302)


# ═══ NUMUNE YÖNETİMİ ═════════════════════════════════════

@router.get("/numune", response_class=HTMLResponse)
def numune_listesi(
    request: Request,
    durum: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(Numune).filter(Numune.firma_id == user.firma_id)
    if durum: q = q.filter(Numune.durum == durum)
    numuneler = q.order_by(Numune.created_at.desc()).all()
    return templates.TemplateResponse("depo/numune.html", {
        "request": request, "user": user,
        "numuneler": numuneler, "NumuneDurum": NumuneDurum,
        "filtre_durum": durum,
    })


@router.post("/numune/{nid}/onayla")
def numune_onayla(
    nid: int,
    rapor_no: str = Form(...),
    sonuc_notu: str = Form(""),
    karar: str = Form("onaylı"),   # onaylı / red
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    nm = db.query(Numune).filter(Numune.id == nid, Numune.firma_id == user.firma_id).first()
    if nm:
        nm.rapor_no     = rapor_no
        nm.sonuc_notu   = sonuc_notu or None
        nm.sonuc_tarihi = datetime.now(timezone.utc)
        nm.onaylayan_id = user.id
        nm.durum        = NumuneDurum.onaylı if karar == "onaylı" else NumuneDurum.red

        # Lot durumunu güncelle
        if nm.lot_id:
            lot = db.query(HammaddeLot).filter(HammaddeLot.id == nm.lot_id).first()
            if lot:
                if karar == "onaylı":
                    lot.durum = LotDurum.onaylı
                    fifo_sirala(db, user.firma_id, lot.hammadde_id)
                else:
                    lot.durum = LotDurum.karantina
                    lot.kalite_notu = f"Numune red: {sonuc_notu}"
                    t = db.query(Tedarikci).filter(Tedarikci.id == lot.tedarikci_id).first()
                    if t: t.karantina_lot += 1
        db.commit()
    return RedirectResponse("/depo/numune", status_code=302)


# ═══ HAREKETLER ══════════════════════════════════════════

@router.get("/hareketler", response_class=HTMLResponse)
def hareketler(
    request: Request,
    depo_id: Optional[int] = Query(None),
    tip: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(DepoHareket).filter(DepoHareket.firma_id == user.firma_id)
    if depo_id: q = q.filter(DepoHareket.depo_id == depo_id)
    if tip:     q = q.filter(DepoHareket.tip == tip)
    hareketler = q.order_by(DepoHareket.tarih.desc()).limit(200).all()
    depolar    = db.query(Depo).filter(Depo.firma_id == user.firma_id).all()
    return templates.TemplateResponse("depo/hareketler.html", {
        "request": request, "user": user,
        "hareketler": hareketler, "depolar": depolar,
        "DepoHareketTip": DepoHareketTip,
        "filtre_depo": depo_id, "filtre_tip": tip,
    })


# ═══ SİLME İŞLEMLERİ (Admin Only) ═══════════════════════

@router.post("/hammadde/sil/{hid}")
def hammadde_sil(
    hid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/depo/hammadde", status_code=302)
    h = db.query(Hammadde).filter(Hammadde.id == hid, Hammadde.firma_id == user.firma_id).first()
    if h:
        h.aktif = False
        db.commit()
    return RedirectResponse("/depo/hammadde", status_code=302)


@router.post("/lot/sil/{lid}")
def lot_sil(
    lid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not (user.is_firma_admin or user.is_super):
        return RedirectResponse("/depo/stok", status_code=302)
    from app.models.models import LotDurum
    lot = db.query(HammaddeLot).filter(HammaddeLot.id == lid, HammaddeLot.firma_id == user.firma_id).first()
    if lot:
        lot.durum = LotDurum.imha
        lot.kalan_miktar = 0
        db.commit()
    return RedirectResponse("/depo/stok", status_code=302)
