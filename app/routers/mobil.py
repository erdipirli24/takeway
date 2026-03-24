"""
Mobil Router
Sahadaki operatörler için sade, dokunmatik-öncelikli arayüz.
- QR kod okutma (kamera)
- Lot sorgulama
- Üretim aşaması tamamlama
- CCP ölçüm girişi
- Numune onayı
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, HammaddeLot, UrunParti, UretimEmri, UretimAsama,
    Numune, NumuneDurum, CCPTanim, CCPOlcum, CCPDurum, LotDurum
)
from app.utils.fifo import fifo_sirala
from decimal import Decimal

router = APIRouter(prefix="/mobil", tags=["mobil"])
templates = Jinja2Templates(directory="app/templates")


# ═══ MOBİL ANA SAYFA ════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
def mobil_anasayfa(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    fid = user.firma_id
    bekleyen_numune = db.query(Numune).filter(
        Numune.firma_id == fid,
        Numune.durum == NumuneDurum.beklemede
    ).count()

    aktif_uretim = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.durum == "devam"
    ).all()

    return templates.TemplateResponse("mobil/anasayfa.html", {
        "request": request, "user": user,
        "bekleyen_numune": bekleyen_numune,
        "aktif_uretim": aktif_uretim,
    })


# ═══ QR OKUTMA ══════════════════════════════════════════

@router.get("/qr", response_class=HTMLResponse)
def qr_okut_sayfasi(request: Request, user: Kullanici = Depends(get_current_user)):
    return templates.TemplateResponse("mobil/qr_okut.html", {
        "request": request, "user": user
    })


@router.get("/qr/sorgula", response_class=HTMLResponse)
def qr_sorgula(
    request: Request,
    kod: str = Query(...),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """QR kodu veya manuel girilen kodu sorgular."""
    fid = user.firma_id
    kod = kod.strip()

    # Lot mu?
    lot = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == fid,
        (HammaddeLot.ic_parti_no == kod) | (HammaddeLot.lot_no == kod)
    ).first()
    if lot:
        return RedirectResponse(f"/mobil/lot/{lot.id}", status_code=302)

    # Ürün partisi mi?
    parti = db.query(UrunParti).filter(
        UrunParti.firma_id == fid,
        UrunParti.parti_no == kod
    ).first()
    if parti:
        return RedirectResponse(f"/mobil/parti/{parti.id}", status_code=302)

    # Üretim emri mi?
    emir = db.query(UretimEmri).filter(
        UretimEmri.firma_id == fid,
        UretimEmri.emri_no == kod
    ).first()
    if emir:
        return RedirectResponse(f"/mobil/uretim/{emir.id}", status_code=302)

    return templates.TemplateResponse("mobil/qr_okut.html", {
        "request": request, "user": user,
        "hata": f"'{kod}' için kayıt bulunamadı."
    })


# ═══ MOBİL LOT DETAY ════════════════════════════════════

@router.get("/lot/{lid}", response_class=HTMLResponse)
def mobil_lot(
    lid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    lot = db.query(HammaddeLot).filter(
        HammaddeLot.id == lid, HammaddeLot.firma_id == user.firma_id
    ).first()
    if not lot:
        return RedirectResponse("/mobil/qr", status_code=302)

    fifo_lotlar = db.query(HammaddeLot).filter(
        HammaddeLot.firma_id == user.firma_id,
        HammaddeLot.hammadde_id == lot.hammadde_id,
        HammaddeLot.durum.in_(["onaylı", "kullanımda", "beklemede"])
    ).order_by(HammaddeLot.kabul_tarihi.asc()).all()
    fifo_konum = next((i+1 for i, l in enumerate(fifo_lotlar) if l.id == lid), None)

    numune = db.query(Numune).filter(
        Numune.lot_id == lid,
        Numune.durum == NumuneDurum.beklemede
    ).first()

    now = datetime.now(timezone.utc)
    return templates.TemplateResponse("mobil/lot_detay.html", {
        "request": request, "user": user,
        "lot": lot, "fifo_konum": fifo_konum,
        "fifo_toplam": len(fifo_lotlar),
        "numune": numune, "now": now,
        "LotDurum": LotDurum,
    })


# ═══ MOBİL ÜRETİM ═══════════════════════════════════════

@router.get("/uretim/{eid}", response_class=HTMLResponse)
def mobil_uretim(
    eid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    emir = db.query(UretimEmri).filter(
        UretimEmri.id == eid, UretimEmri.firma_id == user.firma_id
    ).first()
    if not emir:
        return RedirectResponse("/mobil/", status_code=302)

    ccp_tanimlar = db.query(CCPTanim).filter(
        CCPTanim.firma_id == user.firma_id, CCPTanim.aktif == True
    ).all()

    return templates.TemplateResponse("mobil/uretim.html", {
        "request": request, "user": user,
        "emir": emir,
        "ccp_tanimlar": ccp_tanimlar,
    })


@router.post("/uretim/{eid}/asama/{aid}/tamamla")
def mobil_asama_tamamla(
    eid: int, aid: int,
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    a = db.query(UretimAsama).filter(
        UretimAsama.id == aid, UretimAsama.emir_id == eid
    ).first()
    if a:
        a.tamamlandi = True
        a.bitis      = datetime.now(timezone.utc)
        a.notlar     = notlar or None
        a.sorumlu_id = user.id
        db.commit()
    return RedirectResponse(f"/mobil/uretim/{eid}", status_code=302)


@router.post("/uretim/{eid}/ccp")
def mobil_ccp_olcum(
    eid: int,
    ccp_tanim_id: int = Form(...),
    olculen_deger: float = Form(...),
    birim: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tanim = db.query(CCPTanim).filter(CCPTanim.id == ccp_tanim_id).first()
    durum = CCPDurum.uygun
    if tanim:
        val = Decimal(str(olculen_deger))
        if (tanim.kritik_limit_min and val < Decimal(str(tanim.kritik_limit_min))) or \
           (tanim.kritik_limit_max and val > Decimal(str(tanim.kritik_limit_max))):
            durum = CCPDurum.kritik

    db.add(CCPOlcum(
        firma_id       = user.firma_id,
        ccp_tanim_id   = ccp_tanim_id,
        uretim_emri_id = eid,
        olculen_deger  = olculen_deger,
        birim          = birim or (tanim.birim if tanim else None),
        durum          = durum,
        yapan_id       = user.id,
    ))
    db.commit()
    return RedirectResponse(f"/mobil/uretim/{eid}", status_code=302)


# ═══ MOBİL PARTİ DETAY ══════════════════════════════════

@router.get("/parti/{pid}", response_class=HTMLResponse)
def mobil_parti(
    pid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    parti = db.query(UrunParti).filter(
        UrunParti.id == pid, UrunParti.firma_id == user.firma_id
    ).first()
    if not parti:
        return RedirectResponse("/mobil/qr", status_code=302)

    now = datetime.now(timezone.utc)
    return templates.TemplateResponse("mobil/parti_detay.html", {
        "request": request, "user": user,
        "parti": parti, "now": now,
    })
