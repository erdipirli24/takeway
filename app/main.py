import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import init_db, SessionLocal
from app.routers import auth, dashboard, firma, kullanici, depo, makine, recete, uretim, kalite, satis, sikayet, rapor, vardiya, analiz, mobil, etiket, sistem
from app.models.models import (
    Kullanici, Firma, Depo, Hammadde, HammaddeKategori,
    Tedarikci, FirmaTip, BirimTanim
)
from app.auth import hash_password, tum_yetkiler_olustur


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed()
    yield


def _seed():
    db = SessionLocal()
    try:
        # ── Super Admin ──────────────────────────────────
        if not db.query(Kullanici).filter(Kullanici.is_super == True).first():
            sa = Kullanici(
                firma_id  = None,
                ad_soyad  = "Platform Admin",
                email     = os.environ.get("ADMIN_EMAIL", "admin@traceway.io"),
                hashed_pw = hash_password(os.environ.get("ADMIN_PASSWORD", "Traceway2024!")),
                is_super  = True,
                aktif     = True,
            )
            db.add(sa); db.flush()

        # ── Demo Firma (Elfiga Pastane) ──────────────────
        if not db.query(Firma).filter(Firma.slug == "elfiga").first():
            firma = Firma(
                firma_kodu = "1",
                tip        = FirmaTip.merkez,
                ad         = "Elfiga Pastane Merkez",
                slug       = "elfiga",
                vergi_no   = "1234567890",
                sehir      = "İstanbul",
                email      = "info@elfiga.com",
                aktif      = True,
            )
            db.add(firma); db.flush()

            # Demo şube
            sube = Firma(
                parent_id  = firma.id,
                firma_kodu = "1-1",
                tip        = FirmaTip.sube,
                ad         = "Elfiga Pastane — Kadıköy Şube",
                slug       = "elfiga-kadikoy",
                sehir      = "İstanbul",
                aktif      = True,
            )
            db.add(sube); db.flush()

            # Firma admin
            admin = Kullanici(
                firma_id       = firma.id,
                ad_soyad       = "Patron",
                unvan          = "Genel Müdür",
                email          = "demo@elfiga.com",
                hashed_pw      = hash_password("Demo1234!"),
                is_firma_admin = True,
                aktif          = True,
            )
            db.add(admin); db.flush()
            tum_yetkiler_olustur(db, admin.id, firma_admin=True)

            # Şube admini
            sube_admin = Kullanici(
                firma_id       = sube.id,
                ad_soyad       = "Şube Müdürü",
                unvan          = "Şube Müdürü",
                email          = "kadikoy@elfiga.com",
                hashed_pw      = hash_password("Demo1234!"),
                is_firma_admin = True,
                aktif          = True,
            )
            db.add(sube_admin); db.flush()
            tum_yetkiler_olustur(db, sube_admin.id, firma_admin=True)

            # Gıda mühendisi (kısıtlı yetki)
            muhendis = Kullanici(
                firma_id  = firma.id,
                ad_soyad  = "Ayşe Demir",
                unvan     = "Gıda Mühendisi",
                email     = "ayse@elfiga.com",
                hashed_pw = hash_password("Demo1234!"),
                aktif     = True,
            )
            db.add(muhendis); db.flush()
            tum_yetkiler_olustur(db, muhendis.id, firma_admin=False)

            # Depolar
            kuru = Depo(firma_id=firma.id, ad="Kuru Malzeme Deposu", kod="KD-01", tip="hammadde")
            soguk = Depo(firma_id=firma.id, ad="Soğuk Hava Deposu", kod="SH-01", tip="hammadde", min_sicaklik=0, max_sicaklik=4)
            donuk = Depo(firma_id=firma.id, ad="Derin Dondurucu", kod="DD-01", tip="hammadde", min_sicaklik=-20, max_sicaklik=-18)
            mamul = Depo(firma_id=firma.id, ad="Mamul Deposu", kod="MD-01", tip="mamul")
            db.add_all([kuru, soguk, donuk, mamul]); db.flush()

            # Özel birimler
            for b in [
                BirimTanim(firma_id=firma.id, ad="tepsi", kisaltma="tps", kg_karsiligi=1.800, adet_karsiligi=12),
                BirimTanim(firma_id=firma.id, ad="dilim", kisaltma="dlm", kg_karsiligi=0.150),
                BirimTanim(firma_id=firma.id, ad="porsiyon", kisaltma="prs", kg_karsiligi=0.200),
                BirimTanim(firma_id=firma.id, ad="tabak", kisaltma="tbk", adet_karsiligi=1),
            ]:
                db.add(b)

            # Kategoriler
            un_cat  = HammaddeKategori(firma_id=firma.id, ad="Un & Tahıl",       renk="#f59e0b")
            et_cat  = HammaddeKategori(firma_id=firma.id, ad="Et & Protein",      renk="#ef4444")
            sut_cat = HammaddeKategori(firma_id=firma.id, ad="Süt & Süt Ürünleri",renk="#3b82f6")
            bah_cat = HammaddeKategori(firma_id=firma.id, ad="Baharat & Katkı",   renk="#8b5cf6")
            amb_cat = HammaddeKategori(firma_id=firma.id, ad="Ambalaj",           renk="#6b7280")
            db.add_all([un_cat, et_cat, sut_cat, bah_cat, amb_cat]); db.flush()

            # Hammaddeler
            hm_list = [
                Hammadde(firma_id=firma.id, kategori_id=un_cat.id,  ad="Buğday Unu",         kod="UN-001", birim="kg",    min_stok=200, kritik_stok=50,  alerjenler="gluten",     numune_gerekli=True),
                Hammadde(firma_id=firma.id, kategori_id=un_cat.id,  ad="Nişasta",            kod="NIS-001",birim="kg",    min_stok=50,  kritik_stok=10,  numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=sut_cat.id, ad="Tam Yağlı Süt",      kod="SUT-001",birim="lt",    min_stok=100, kritik_stok=20,  alerjenler="sut",        numune_gerekli=True),
                Hammadde(firma_id=firma.id, kategori_id=sut_cat.id, ad="Tereyağı",           kod="TYG-001",birim="kg",    min_stok=50,  kritik_stok=10,  alerjenler="sut",        numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=sut_cat.id, ad="Yumurta",            kod="YUM-001",birim="adet",  min_stok=500, kritik_stok=100, alerjenler="yumurta",    numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=bah_cat.id, ad="Toz Şeker",          kod="TSK-001",birim="kg",    min_stok=100, kritik_stok=20,  numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=bah_cat.id, ad="Çikolata Damla",     kod="CKL-001",birim="kg",    min_stok=20,  kritik_stok=5,   numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=bah_cat.id, ad="Vanilya Özü",        kod="VNL-001",birim="lt",    min_stok=2,   kritik_stok=0.5, numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=amb_cat.id, ad="Kutu 500g",          kod="AMB-001",birim="adet",  min_stok=1000,kritik_stok=200, numune_gerekli=False),
                Hammadde(firma_id=firma.id, kategori_id=et_cat.id,  ad="Dana Kıyma",         kod="ET-001", birim="kg",    min_stok=50,  kritik_stok=10,  numune_gerekli=True),
            ]
            db.add_all(hm_list)

            # Tedarikçiler
            db.add_all([
                Tedarikci(firma_id=firma.id, ad="Söke Un Fabrikası",   kod="TDR-001", vergi_no="1111111111"),
                Tedarikci(firma_id=firma.id, ad="Pınar Süt A.Ş.",      kod="TDR-002", vergi_no="2222222222"),
                Tedarikci(firma_id=firma.id, ad="Callebaut Çikolata",   kod="TDR-003", vergi_no="3333333333"),
                Tedarikci(firma_id=firma.id, ad="Güven Et A.Ş.",        kod="TDR-004", vergi_no="4444444444"),
            ])

            db.commit()
            print("[SEED] Demo kurulum tamamlandı")
            print("[SEED] Merkez:  demo@elfiga.com / Demo1234!")
            print("[SEED] Şube:    kadikoy@elfiga.com / Demo1234!")
    except Exception as e:
        db.rollback()
        print(f"[SEED] Hata: {e}")
        import traceback; traceback.print_exc()
    finally:
        db.close()


app = FastAPI(title="TraceWay", version="2.0.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(firma.router)
app.include_router(kullanici.router)
app.include_router(depo.router)
app.include_router(makine.router)
app.include_router(recete.router)
app.include_router(uretim.router)
app.include_router(kalite.router)
app.include_router(satis.router)
app.include_router(sikayet.router)
app.include_router(rapor.router)
app.include_router(vardiya.router)
app.include_router(analiz.router)
app.include_router(mobil.router)
app.include_router(etiket.router)
app.include_router(sistem.router)



