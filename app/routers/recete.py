from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates_config import templates, safe_float, safe_int
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models.models import (
    Kullanici, Recete, ReceteKalem, ReceteTip,
    Hammadde, Urun, BirimTanim, Modul,
    YariMamul, YariMamulDurum
)
from app.auth import kullanici_yetki

router = APIRouter(prefix="/recete", tags=["recete"])

SISTEM_BIRIMLERI = ["kg", "g", "lt", "ml", "adet"]


def _birimleri_getir(db: Session, firma_id: int) -> List[str]:
    ozel = [b.ad for b in db.query(BirimTanim).filter(
        BirimTanim.firma_id == firma_id, BirimTanim.aktif == True
    ).all()]
    return SISTEM_BIRIMLERI + ozel


@router.get("/", response_class=HTMLResponse)
def recete_listesi(
    request: Request,
    tip: Optional[str] = Query(None),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not kullanici_yetki(user, Modul.recete):
        return RedirectResponse("/", status_code=302)

    q = db.query(Recete).filter(Recete.firma_id == user.firma_id, Recete.aktif == True)
    if tip:
        q = q.filter(Recete.tip == tip)
    receteler = q.order_by(Recete.ad).all()

    return templates.TemplateResponse("recete/liste.html", {
        "request": request, "user": user,
        "receteler": receteler,
        "ReceteTip": ReceteTip,
        "filtre_tip": tip,
        "can_edit": kullanici_yetki(user, Modul.recete_duzenle, giris=True),
    })


@router.get("/yeni", response_class=HTMLResponse)
def recete_yeni_form(
    request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not kullanici_yetki(user, Modul.recete_duzenle, giris=True):
        return RedirectResponse("/recete/", status_code=302)

    fid = user.firma_id
    return templates.TemplateResponse("recete/form.html", {
        "request": request, "user": user,
        "urunler":     db.query(Urun).filter(Urun.firma_id == fid, Urun.aktif == True).all(),
        "hammaddeler": db.query(Hammadde).filter(Hammadde.firma_id == fid, Hammadde.aktif == True).order_by(Hammadde.ad).all(),
        "ara_urunler": db.query(Recete).filter(Recete.firma_id == fid, Recete.tip == ReceteTip.karisim, Recete.onaylandi == True, Recete.aktif == True).all(),
        "yari_mamuller": db.query(YariMamul).filter(YariMamul.firma_id == fid, YariMamul.durum == YariMamulDurum.stokta, YariMamul.kalan_miktar > 0).order_by(YariMamul.ad).all(),
        "birimler":    _birimleri_getir(db, fid),
        "ReceteTip":   ReceteTip,
        "recete":      None,
    })


@router.post("/kaydet")
async def recete_kaydet(
    request: Request,
    ad: str = Form(...),
    tip: str = Form("hammadde"),
    urun_id: str = Form(""),
    baz_miktar: float = Form(1),
    baz_birim: str = Form("kg"),
    baz_kg_karsiligi: str = Form(""),
    notlar: str = Form(""),
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not kullanici_yetki(user, Modul.recete_duzenle, giris=True):
        return RedirectResponse("/recete/", status_code=302)

    fid  = user.firma_id
    form = await request.form()

    # Versiyon: aynı ürüne/adına ait önceki var mı?
    onceki = db.query(Recete).filter(
        Recete.firma_id == fid,
        Recete.ad == ad,
        Recete.aktif == True
    ).order_by(Recete.versiyon.desc()).first()
    versiyon = (onceki.versiyon + 1) if onceki else 1

    # Güvenli float dönüşüm
    _baz_kg = None
    if baz_kg_karsiligi and baz_kg_karsiligi.strip():
        try: _baz_kg = float(baz_kg_karsiligi.replace(",", "."))
        except: _baz_kg = None

    recete = Recete(
        firma_id          = fid,
        urun_id           = safe_int(urun_id),
        ad                = ad,
        tip               = tip,
        versiyon          = versiyon,
        aktif             = True,
        baz_miktar        = baz_miktar,
        baz_birim         = baz_birim,
        baz_kg_karsiligi  = _baz_kg,
        notlar            = notlar or None,
        onaylandi         = False,
        created_by        = user.id,
    )
    db.add(recete); db.flush()

    # Kalemleri parse et — form'dan dinamik gelir
    # Format: kalem_hammadde_0, kalem_miktar_0, kalem_birim_0, kalem_sira_0
    i = 0
    while f"kalem_miktar_{i}" in form or f"kalem_malzeme_{i}" in form:
        if f"kalem_miktar_{i}" not in form:
            i += 1
            continue
        miktar    = float(form.get(f"kalem_miktar_{i}", 0) or 0)
        birim     = form.get(f"kalem_birim_{i}", "kg")
        tolerans  = float(form.get(f"kalem_tolerans_{i}", 5) or 5)
        notlar_k  = form.get(f"kalem_not_{i}", "")
        zorunlu   = True

        # Yeni format: kalem_malzeme_N = h_ID | r_ID | y_ID
        malzeme_val = form.get(f"kalem_malzeme_{i}", "")
        hm_id = None
        ara_id = None
        if malzeme_val.startswith("h_"):
            hm_id = malzeme_val[2:]
        elif malzeme_val.startswith("r_"):
            ara_id = malzeme_val  # r_ prefix ile eski parser'a gönder
        elif malzeme_val.startswith("y_"):
            ara_id = malzeme_val  # y_ prefix
        else:
            # Eski format uyumluluğu
            hm_id = form.get(f"kalem_hammadde_{i}")
            ara_id = form.get(f"kalem_ara_{i}")

        # ara_id prefix: r_=recete, y_=yari_mamul (yari mamul için recete_id olarak ara_id saklıyoruz)
        _ara_recete_id = None
        if ara_id and ara_id.strip():
            raw = ara_id.strip()
            if raw.startswith('r_'):
                try: _ara_recete_id = int(raw[2:])
                except: pass
            elif raw.startswith('y_'):
                # Yarı mamul — şimdilik recete_id olarak sakla, negatif id ile ayırt et
                # Gerçek çözüm: notlar'a "ym:ID" yaz
                try:
                    ym_id = int(raw[2:])
                    notlar_k = f"ym:{ym_id}" + (f" {notlar_k}" if notlar_k else "")
                except: pass
            else:
                try: _ara_recete_id = int(raw)
                except: pass

        if miktar > 0 and (hm_id or _ara_recete_id or (notlar_k and notlar_k.startswith('ym:'))):
            db.add(ReceteKalem(
                recete_id          = recete.id,
                hammadde_id        = int(hm_id) if hm_id else None,
                ara_urun_recete_id = _ara_recete_id,
                sira               = i + 1,
                miktar             = miktar,
                birim              = birim,
                zorunlu            = zorunlu,
                tolerans_yuzde     = tolerans,
                notlar             = notlar_k or None,
            ))
        i += 1

    db.commit()
    return RedirectResponse(f"/recete/{recete.id}", status_code=302)


@router.get("/{rid}", response_class=HTMLResponse)
def recete_detay(
    rid: int, request: Request,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not kullanici_yetki(user, Modul.recete):
        return RedirectResponse("/", status_code=302)

    recete = db.query(Recete).filter(Recete.id == rid, Recete.firma_id == user.firma_id).first()
    if not recete:
        return RedirectResponse("/recete/", status_code=302)

    # Aynı adın tüm versiyonları
    versiyonlar = db.query(Recete).filter(
        Recete.firma_id == user.firma_id,
        Recete.ad == recete.ad,
    ).order_by(Recete.versiyon.desc()).all()

    return templates.TemplateResponse("recete/detay.html", {
        "request": request, "user": user,
        "recete": recete,
        "versiyonlar": versiyonlar,
        "can_edit": kullanici_yetki(user, Modul.recete_duzenle, giris=True),
    })


@router.post("/{rid}/onayla")
def recete_onayla(
    rid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not kullanici_yetki(user, Modul.recete_duzenle, giris=True):
        return RedirectResponse("/recete/", status_code=302)

    recete = db.query(Recete).filter(Recete.id == rid, Recete.firma_id == user.firma_id).first()
    if recete and not recete.onaylandi:
        recete.onaylandi    = True
        recete.onaylayan_id = user.id
        recete.onay_tarihi  = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(f"/recete/{rid}", status_code=302)


@router.post("/{rid}/arsivle")
def recete_arsivle(
    rid: int,
    user: Kullanici = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not kullanici_yetki(user, Modul.recete_duzenle, giris=True):
        return RedirectResponse("/recete/", status_code=302)

    recete = db.query(Recete).filter(Recete.id == rid, Recete.firma_id == user.firma_id).first()
    if recete:
        recete.aktif = False
        db.commit()
    return RedirectResponse("/recete/", status_code=302)


# ─── ÜRÜN TANIMLAR ───────────────────────────────────────

@router.get("/urun/liste", response_class=HTMLResponse)
def urun_listesi(request: Request, user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)):
    urunler = db.query(Urun).filter(Urun.firma_id == user.firma_id, Urun.aktif == True).order_by(Urun.ad).all()
    birimler = _birimleri_getir(db, user.firma_id)
    return templates.TemplateResponse("recete/urunler.html", {
        "request": request, "user": user,
        "urunler": urunler, "birimler": birimler,
    })


@router.post("/urun/ekle")
def urun_ekle(
    ad: str = Form(...), kod: str = Form(""), barkod: str = Form(""),
    birim: str = Form("kg"), kdv_oran: float = Form(10),
    raf_omru_gun: Optional[int] = Form(None), aciklama: str = Form(""),
    user: Kullanici = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.add(Urun(
        firma_id=user.firma_id, ad=ad, kod=kod or None,
        barkod=barkod or None, birim=birim, kdv_oran=kdv_oran,
        raf_omru_gun=safe_int(raf_omru_gun), aciklama=aciklama or None
    ))
    db.commit()
    return RedirectResponse("/recete/urun/liste", status_code=302)
