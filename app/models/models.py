"""
TraceWay — Faz 1 Veritabanı Modeli
====================================
Firma/Şube hiyerarşisi, modül bazlı yetki matrisi,
hammadde & depo yönetimi, FIFO stok.
"""
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Boolean, Numeric, Enum as SAEnum, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()


# ═══════════════════════════════════════════════════════════
#  ENUM'LAR
# ═══════════════════════════════════════════════════════════

class FirmaTip(str, enum.Enum):
    merkez = "merkez"
    sube   = "sube"

class LotDurum(str, enum.Enum):
    beklemede  = "beklemede"   # Kabul edildi, numune bekleniyor
    onaylı     = "onaylı"      # Kullanıma hazır
    kullanımda = "kullanımda"  # FIFO ile çekilmeye başlandı
    tükendi    = "tükendi"     # Kalan = 0
    karantina  = "karantina"   # Durduruldu
    iade       = "iade"
    imha       = "imha"

class DepoHareketTip(str, enum.Enum):
    giris      = "giris"
    cikis      = "cikis"
    transfer   = "transfer"
    sayim_fark = "sayim_fark"
    fire       = "fire"
    karantina  = "karantina"
    iade_giris = "iade_giris"

class NumuneTip(str, enum.Enum):
    hammadde = "hammadde"
    uretim   = "uretim"
    final    = "final"

class NumuneDurum(str, enum.Enum):
    beklemede = "beklemede"
    onaylı    = "onaylı"
    red       = "red"

class NumuneLab(str, enum.Enum):
    dahili = "dahili"
    harici = "harici"

# Sistemdeki tüm modüller — yetki matrisi için
class Modul(str, enum.Enum):
    dashboard        = "dashboard"
    depo_stok        = "depo_stok"
    hammadde_giris   = "hammadde_giris"
    uretim           = "uretim"
    recete           = "recete"
    recete_duzenle   = "recete_duzenle"   # ayrı yetki
    karisim          = "karisim"
    kalite_numune    = "kalite_numune"
    makine           = "makine"
    satis_sevkiyat   = "satis_sevkiyat"
    sikayet_recall   = "sikayet_recall"
    raporlar         = "raporlar"
    kullanici_yonet  = "kullanici_yonet"
    firma_ayarlar    = "firma_ayarlar"


# ═══════════════════════════════════════════════════════════
#  FİRMA & ŞUBE
# ═══════════════════════════════════════════════════════════

class Firma(Base):
    """
    Hem merkez hem şube bu tabloda.
    Şube ise parent_id dolu, tip='sube'.
    Şube kodu: parent.id + '-' + sira  →  "2-1", "2-2"
    """
    __tablename__ = "firmalar"

    id          = Column(Integer, primary_key=True)
    parent_id   = Column(Integer, ForeignKey("firmalar.id"), nullable=True)
    tip         = Column(SAEnum(FirmaTip), default=FirmaTip.merkez)
    firma_kodu  = Column(String(20), unique=True, nullable=False)  # "2", "2-1", "2-2"
    ad          = Column(String(150), nullable=False)
    slug        = Column(String(80), unique=True, nullable=False)
    vergi_no    = Column(String(20))
    adres       = Column(Text)
    sehir       = Column(String(80))
    email       = Column(String(150))
    telefon     = Column(String(30))
    aktif       = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # İlişkiler
    parent      = relationship("Firma", remote_side=[id], back_populates="subeler")
    subeler     = relationship("Firma", back_populates="parent")

    kullanicilar   = relationship("Kullanici", back_populates="firma", cascade="all,delete")
    depolar        = relationship("Depo", back_populates="firma", cascade="all,delete")
    hammaddeler    = relationship("Hammadde", back_populates="firma", cascade="all,delete")
    kategoriler    = relationship("HammaddeKategori", back_populates="firma", cascade="all,delete")
    tedarikciler   = relationship("Tedarikci", back_populates="firma", cascade="all,delete")
    lotlar         = relationship("HammaddeLot", back_populates="firma")
    numuneler      = relationship("Numune", back_populates="firma")
    birimler       = relationship("BirimTanim", back_populates="firma", cascade="all,delete")


# ═══════════════════════════════════════════════════════════
#  KULLANICI & YETKİ MATRİSİ
# ═══════════════════════════════════════════════════════════

class Kullanici(Base):
    __tablename__ = "kullanicilar"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=True)  # null = super_admin
    ad_soyad    = Column(String(100), nullable=False)
    unvan       = Column(String(100))   # "Gıda Mühendisi", "Depo Sorumlusu" vb.
    email       = Column(String(150), unique=True, nullable=False)
    hashed_pw   = Column(String(200), nullable=False)
    is_super    = Column(Boolean, default=False)   # platform sahibi
    is_firma_admin = Column(Boolean, default=False) # firma patronu
    aktif       = Column(Boolean, default=True)
    last_login  = Column(DateTime(timezone=True))
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    firma       = relationship("Firma", back_populates="kullanicilar")
    yetkiler    = relationship("KullaniciYetki", back_populates="kullanici",
                               cascade="all,delete", lazy="selectin")


class KullaniciYetki(Base):
    """
    Modül bazlı yetki matrisi.
    Her satır: kullanici X, modul Y için gore=True/False, giris=True/False
    """
    __tablename__ = "kullanici_yetkiler"

    id           = Column(Integer, primary_key=True)
    kullanici_id = Column(Integer, ForeignKey("kullanicilar.id"), nullable=False)
    modul        = Column(SAEnum(Modul), nullable=False)
    gorebilir    = Column(Boolean, default=False)
    giris_yapabilir = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("kullanici_id", "modul", name="uq_kullanici_modul"),
    )

    kullanici    = relationship("Kullanici", back_populates="yetkiler")


# ═══════════════════════════════════════════════════════════
#  BİRİM TANIM (serbest birimler)
# ═══════════════════════════════════════════════════════════

class BirimTanim(Base):
    """
    Firma bazlı özel birim tanımları.
    Temel birimler (kg, g, lt, ml, adet) sistem genelinde geçerli.
    Pastane için: tepsi, dilim, porsiyon, tabak vb. buraya eklenir.
    """
    __tablename__ = "birim_tanimlar"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(40), nullable=False)   # "tepsi"
    kisaltma    = Column(String(10))                   # "tps"
    kg_karsiligi = Column(Numeric(10,4), nullable=True) # 1 tepsi = kaç kg (opsiyonel)
    adet_karsiligi = Column(Numeric(10,2), nullable=True) # 1 tepsi = kaç adet
    aciklama    = Column(String(200))
    aktif       = Column(Boolean, default=True)

    firma       = relationship("Firma", back_populates="birimler")


# ═══════════════════════════════════════════════════════════
#  ALERJENler
# ═══════════════════════════════════════════════════════════

ALERJEN_LISTESI = [
    "gluten", "kabuklu_deniz", "yumurta", "balik",
    "yer_fistigi", "soya", "sut", "findik",
    "kereviz", "hardal", "susam", "kuprit",
    "lupine", "yumusakcalar"
]


# ═══════════════════════════════════════════════════════════
#  DEPO
# ═══════════════════════════════════════════════════════════

class Depo(Base):
    __tablename__ = "depolar"

    id           = Column(Integer, primary_key=True)
    firma_id     = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad           = Column(String(100), nullable=False)
    kod          = Column(String(20))
    tip          = Column(String(30), default="hammadde")  # hammadde/mamul/yari_mamul/genel
    adres        = Column(Text)
    min_sicaklik = Column(Numeric(5,1))
    max_sicaklik = Column(Numeric(5,1))
    aktif        = Column(Boolean, default=True)
    notlar       = Column(Text)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    firma        = relationship("Firma", back_populates="depolar")
    stoklar      = relationship("DepoStok", back_populates="depo", cascade="all,delete")
    hareketler   = relationship("DepoHareket", foreign_keys="[DepoHareket.depo_id]", back_populates="depo")


class DepoStok(Base):
    """Lot bazlı anlık stok — FIFO için kabul_tarihi sıralı"""
    __tablename__ = "depo_stok"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    depo_id     = Column(Integer, ForeignKey("depolar.id"), nullable=False)
    lot_id      = Column(Integer, ForeignKey("hammadde_lotlar.id"), nullable=False)
    miktar      = Column(Numeric(14,3), nullable=False, default=0)
    guncellendi = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("depo_id", "lot_id", name="uq_depo_lot"),)

    depo        = relationship("Depo", back_populates="stoklar")
    lot         = relationship("HammaddeLot", back_populates="depo_stoklar")


class DepoHareket(Base):
    """Her lot için kronolojik hareket — tam iz"""
    __tablename__ = "depo_hareketler"

    id             = Column(Integer, primary_key=True)
    firma_id       = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    depo_id        = Column(Integer, ForeignKey("depolar.id"), nullable=False)
    lot_id         = Column(Integer, ForeignKey("hammadde_lotlar.id"), nullable=False)
    tip            = Column(SAEnum(DepoHareketTip), nullable=False)
    miktar         = Column(Numeric(14,3), nullable=False)
    onceki_miktar  = Column(Numeric(14,3))
    sonraki_miktar = Column(Numeric(14,3))
    kaynak_depo_id = Column(Integer, ForeignKey("depolar.id"), nullable=True)
    hedef_depo_id  = Column(Integer, ForeignKey("depolar.id"), nullable=True)
    aciklama       = Column(Text)
    tarih          = Column(DateTime(timezone=True), server_default=func.now())
    yapan_id       = Column(Integer, ForeignKey("kullanicilar.id"))

    depo           = relationship("Depo", foreign_keys="[DepoHareket.depo_id]", back_populates="hareketler")
    lot            = relationship("HammaddeLot", back_populates="hareketler")


# ═══════════════════════════════════════════════════════════
#  TEDARİKÇİ
# ═══════════════════════════════════════════════════════════

class Tedarikci(Base):
    __tablename__ = "tedarikciler"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(150), nullable=False)
    kod         = Column(String(30))
    vergi_no    = Column(String(20))
    email       = Column(String(150))
    telefon     = Column(String(30))
    adres       = Column(Text)
    aktif       = Column(Boolean, default=True)
    # Performans skoru (otomatik hesaplanır)
    toplam_lot      = Column(Integer, default=0)
    karantina_lot   = Column(Integer, default=0)
    iade_lot        = Column(Integer, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    firma       = relationship("Firma", back_populates="tedarikciler")
    lotlar      = relationship("HammaddeLot", back_populates="tedarikci")


# ═══════════════════════════════════════════════════════════
#  HAMMADDE KATEGORİ & TANIMLAR
# ═══════════════════════════════════════════════════════════

class HammaddeKategori(Base):
    __tablename__ = "hammadde_kategoriler"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(80), nullable=False)
    renk        = Column(String(10), default="#6366f1")

    firma       = relationship("Firma", back_populates="kategoriler")
    hammaddeler = relationship("Hammadde", back_populates="kategori")


class Hammadde(Base):
    __tablename__ = "hammaddeler"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    kategori_id     = Column(Integer, ForeignKey("hammadde_kategoriler.id"), nullable=True)
    ad              = Column(String(150), nullable=False)
    kod             = Column(String(50))
    birim           = Column(String(30), default="kg")
    min_stok        = Column(Numeric(14,3), default=0)
    kritik_stok     = Column(Numeric(14,3), default=0)
    aciklama        = Column(Text)
    aktif           = Column(Boolean, default=True)

    # Allerjenler (virgülle ayrılmış liste)
    alerjenler      = Column(String(500), default="")
    # Numune gerekli mi?
    numune_gerekli  = Column(Boolean, default=True)

    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    firma           = relationship("Firma", back_populates="hammaddeler")
    kategori        = relationship("HammaddeKategori", back_populates="hammaddeler")
    lotlar          = relationship("HammaddeLot", back_populates="hammadde", cascade="all,delete")

    @property
    def alerjen_listesi(self):
        if not self.alerjenler:
            return []
        return [a.strip() for a in self.alerjenler.split(",") if a.strip()]


# ═══════════════════════════════════════════════════════════
#  HAMMADDE LOT (FIFO)
# ═══════════════════════════════════════════════════════════

class HammaddeLot(Base):
    """
    FIFO Kuralı: kabul_tarihi ASC → en eski lot önce tükenir.
    Numune gerekli hammaddeler → durum='beklemede' başlar,
    numune onaylanınca → 'onaylı' olur, FIFO'ya girer.
    """
    __tablename__ = "hammadde_lotlar"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    hammadde_id     = Column(Integer, ForeignKey("hammaddeler.id"), nullable=False)
    tedarikci_id    = Column(Integer, ForeignKey("tedarikciler.id"), nullable=True)
    depo_id         = Column(Integer, ForeignKey("depolar.id"), nullable=True)

    # Kimlik
    lot_no          = Column(String(80), nullable=False)    # tedarikçi lot no
    ic_parti_no     = Column(String(80))                    # otomatik iç parti
    fifo_sira       = Column(Integer)                       # hesaplanan FIFO sırası

    # Fatura
    fatura_no       = Column(String(60))
    fatura_tarihi   = Column(DateTime(timezone=True))

    # Miktarlar
    giris_miktar    = Column(Numeric(14,3), nullable=False)
    kalan_miktar    = Column(Numeric(14,3), nullable=False)
    birim           = Column(String(30), default="kg")

    # Fiyat
    birim_fiyat     = Column(Numeric(14,4))
    para_birimi     = Column(String(5), default="TRY")

    # Durum & Kalite
    durum           = Column(SAEnum(LotDurum), default=LotDurum.beklemede)
    kalite_notu     = Column(Text)

    # Tarihler
    uretim_tarihi   = Column(DateTime(timezone=True))
    son_kullanma    = Column(DateTime(timezone=True))
    kabul_tarihi    = Column(DateTime(timezone=True), server_default=func.now())

    # Depo konumu
    depo_konumu     = Column(String(100))

    # Belgeler
    sertifika_no    = Column(String(100))

    # QR
    qr_data         = Column(Text)

    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    __table_args__ = (
        Index("ix_lot_hammadde_fifo", "hammadde_id", "kabul_tarihi"),
    )

    firma           = relationship("Firma", back_populates="lotlar")
    hammadde        = relationship("Hammadde", back_populates="lotlar")
    tedarikci       = relationship("Tedarikci", back_populates="lotlar")
    depo_stoklar    = relationship("DepoStok", back_populates="lot")
    hareketler      = relationship("DepoHareket", back_populates="lot")
    numuneler       = relationship("Numune", back_populates="lot")


# ═══════════════════════════════════════════════════════════
#  NUMUNE & LAB
# ═══════════════════════════════════════════════════════════

class Numune(Base):
    """
    Hammadde girişinde veya üretim aşamasında alınan numune.
    Onaylanmadan lot kullanıma girmez.
    """
    __tablename__ = "numuneler"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    lot_id          = Column(Integer, ForeignKey("hammadde_lotlar.id"), nullable=True)
    tip             = Column(SAEnum(NumuneTip), nullable=False)
    lab_tipi        = Column(SAEnum(NumuneLab), default=NumuneLab.dahili)
    durum           = Column(SAEnum(NumuneDurum), default=NumuneDurum.beklemede)

    numune_no       = Column(String(60), nullable=False)   # otomatik
    miktar          = Column(Numeric(10,3))
    birim           = Column(String(20), default="g")

    # Sonuç
    rapor_no        = Column(String(100))
    rapor_dosya     = Column(String(300))   # harici PDF yolu
    sonuc_notu      = Column(Text)

    # Tarihler
    alinma_tarihi   = Column(DateTime(timezone=True), server_default=func.now())
    sonuc_tarihi    = Column(DateTime(timezone=True))

    alan_id         = Column(Integer, ForeignKey("kullanicilar.id"))
    onaylayan_id    = Column(Integer, ForeignKey("kullanicilar.id"))
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    # QR (numune etiketi için)
    qr_data         = Column(Text)

    firma           = relationship("Firma", back_populates="numuneler")
    lot             = relationship("HammaddeLot", back_populates="numuneler")


# ═══════════════════════════════════════════════════════════
#  FAZ 2 — MAKINE, REÇETE, KARIşIM, ÜRETİM
# ═══════════════════════════════════════════════════════════

class MacineDurum(str, enum.Enum):
    aktif   = "aktif"
    arizali = "arizali"
    bakim   = "bakim"
    pasif   = "pasif"

class ReceteTip(str, enum.Enum):
    hammadde  = "hammadde"   # direkt hammaddeden ürün
    karisim   = "karisim"    # ara ürün (hamur, krema, sos)
    kombine   = "kombine"    # hem hammadde hem ara ürün

class UretimDurum(str, enum.Enum):
    taslak     = "taslak"
    planlandı  = "planlandı"
    devam      = "devam"
    beklemede  = "beklemede"  # hammadde bekleniyor
    tamamlandı = "tamamlandı"
    iptal      = "iptal"

class YariMamulDurum(str, enum.Enum):
    stokta   = "stokta"
    kullanımda = "kullanımda"
    tukendi  = "tukendi"
    fire     = "fire"


# ─── MAKİNE ──────────────────────────────────────────────

class Makine(Base):
    __tablename__ = "makineler"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad              = Column(String(120), nullable=False)
    kod             = Column(String(30))
    tip             = Column(String(60))          # Fırın, Mikser, Hamur Açma, Paketleme...
    marka           = Column(String(80))
    model           = Column(String(80))
    seri_no         = Column(String(80))
    kapasite        = Column(String(60))          # "50 kg/saat", "3 tepsi"
    durum           = Column(SAEnum(MacineDurum), default=MacineDurum.aktif)
    son_bakim       = Column(DateTime(timezone=True))
    sonraki_bakim   = Column(DateTime(timezone=True))
    bakim_notu      = Column(Text)
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    firma           = relationship("Firma")
    uretim_atamalari = relationship("UretimMakineAtama", back_populates="makine")


class MakineBakimKaydi(Base):
    __tablename__ = "makine_bakim_kayitlari"

    id          = Column(Integer, primary_key=True)
    makine_id   = Column(Integer, ForeignKey("makineler.id"), nullable=False)
    tarih       = Column(DateTime(timezone=True), server_default=func.now())
    tip         = Column(String(60))              # Periyodik, Arıza, Kalibrasyon
    aciklama    = Column(Text)
    yapan       = Column(String(100))
    maliyet     = Column(Numeric(10,2))
    created_by  = Column(Integer, ForeignKey("kullanicilar.id"))

    makine      = relationship("Makine")


# ─── ÜRÜN TANIMI ─────────────────────────────────────────

class Urun(Base):
    """Üretilen nihai ürün tanımları."""
    __tablename__ = "urunler"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(150), nullable=False)
    kod         = Column(String(50))
    barkod      = Column(String(60))
    birim       = Column(String(30), default="kg")
    kdv_oran    = Column(Numeric(5,2), default=10)
    raf_omru_gun = Column(Integer)                # gün cinsinden
    aciklama    = Column(Text)
    aktif       = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    firma       = relationship("Firma")
    receteler   = relationship("Recete", back_populates="urun")


# ─── REÇETE ──────────────────────────────────────────────

class Recete(Base):
    """
    Reçete bir kez onaylandıktan sonra değiştirilemez.
    Değişiklik → yeni versiyon açılır, eskisi arşivde kalır.
    Sadece recete_duzenle yetkisi olan kişiler onaylayabilir.
    """
    __tablename__ = "receteler"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    urun_id         = Column(Integer, ForeignKey("urunler.id"), nullable=True)   # null = ara ürün reçetesi
    ad              = Column(String(150), nullable=False)
    tip             = Column(SAEnum(ReceteTip), default=ReceteTip.hammadde)
    versiyon        = Column(Integer, default=1)
    aktif           = Column(Boolean, default=True)   # false = arşiv

    # Baz birim — reçetenin "1 birim" çıktısı
    baz_miktar      = Column(Numeric(10,3), default=1)
    baz_birim       = Column(String(30), default="kg")   # kg, tepsi, adet, porsiyon...
    baz_kg_karsiligi = Column(Numeric(10,4))              # 1 tepsi = 1.8 kg

    onaylandi       = Column(Boolean, default=False)
    onaylayan_id    = Column(Integer, ForeignKey("kullanicilar.id"), nullable=True)
    onay_tarihi     = Column(DateTime(timezone=True))
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    firma           = relationship("Firma")
    urun            = relationship("Urun", back_populates="receteler")
    kalemler        = relationship("ReceteKalem", foreign_keys='recete_kalemler.c.recete_id', back_populates="recete", cascade="all,delete")


class ReceteKalem(Base):
    """
    Reçete içindeki hammadde veya ara ürün kalemi.
    Miktar her zaman temel birimde (kg/lt/adet).
    """
    __tablename__ = "recete_kalemler"

    id              = Column(Integer, primary_key=True)
    recete_id       = Column(Integer, ForeignKey("receteler.id"), nullable=False)
    hammadde_id     = Column(Integer, ForeignKey("hammaddeler.id"), nullable=True)
    ara_urun_recete_id = Column(Integer, ForeignKey("receteler.id"), nullable=True)  # karışım modu
    sira            = Column(Integer, default=1)
    miktar          = Column(Numeric(14,4), nullable=False)   # baz birim başına
    birim           = Column(String(30), default="kg")
    zorunlu         = Column(Boolean, default=True)
    tolerans_yuzde  = Column(Numeric(5,2), default=5)         # ±% tolerans
    notlar          = Column(String(200))

    recete          = relationship("Recete", foreign_keys='recete_kalemler.c.recete_id', back_populates="kalemler")
    hammadde        = relationship("Hammadde")
    ara_urun_recete = relationship("Recete", foreign_keys='recete_kalemler.c.ara_urun_recete_id')


# ─── ARA ÜRÜN (KARIşIM) ──────────────────────────────────

class YariMamul(Base):
    """
    Karışım modunda üretilen ara ürün partisi.
    Raf ömrü dolunca otomatik fire.
    Örnek: Temel Kurabiye Hamuru — 8 kg — 2 gün raf ömrü
    """
    __tablename__ = "yari_mamuller"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    recete_id       = Column(Integer, ForeignKey("receteler.id"), nullable=False)
    uretim_emri_id  = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=True)

    parti_no        = Column(String(80), nullable=False, unique=True)
    ad              = Column(String(150))                       # "Temel Kurabiye Hamuru"
    uretim_miktari  = Column(Numeric(14,3), nullable=False)
    kalan_miktar    = Column(Numeric(14,3), nullable=False)
    birim           = Column(String(30), default="kg")

    durum           = Column(SAEnum(YariMamulDurum), default=YariMamulDurum.stokta)
    raf_omru_gun    = Column(Integer, nullable=False)           # girilmesi zorunlu
    uretim_tarihi   = Column(DateTime(timezone=True), server_default=func.now())
    son_kullanma    = Column(DateTime(timezone=True))           # uretim + raf_omru

    depo_id         = Column(Integer, ForeignKey("depolar.id"), nullable=True)
    qr_data         = Column(Text)
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    recete          = relationship("Recete")
    uretim_emri     = relationship("UretimEmri", back_populates="yari_mamul_kaydi")
    kullanim_kayitlari = relationship("YariMamulKullanim", back_populates="yari_mamul")


class YariMamulKullanim(Base):
    """Hangi üretimde ne kadar yarı mamul kullanıldı."""
    __tablename__ = "yari_mamul_kullanim"

    id              = Column(Integer, primary_key=True)
    yari_mamul_id   = Column(Integer, ForeignKey("yari_mamuller.id"), nullable=False)
    uretim_emri_id  = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=False)
    kullanilan      = Column(Numeric(14,3), nullable=False)
    tarih           = Column(DateTime(timezone=True), server_default=func.now())
    yapan_id        = Column(Integer, ForeignKey("kullanicilar.id"))

    yari_mamul      = relationship("YariMamul", back_populates="kullanim_kayitlari")


# ─── ÜRETİM EMRİ ─────────────────────────────────────────

class UretimEmri(Base):
    __tablename__ = "uretim_emirleri"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    recete_id       = Column(Integer, ForeignKey("receteler.id"), nullable=True)
    urun_id         = Column(Integer, ForeignKey("urunler.id"), nullable=True)

    emri_no         = Column(String(60), nullable=False, unique=True)
    urun_adi        = Column(String(150))

    # Birim — tepsi, kg, adet gibi
    hedef_miktar    = Column(Numeric(14,3), nullable=False)
    hedef_birim     = Column(String(30), default="kg")
    uretilen_miktar = Column(Numeric(14,3), default=0)

    durum           = Column(SAEnum(UretimDurum), default=UretimDurum.planlandı)
    oncelik         = Column(Integer, default=2)               # 1=yüksek 2=normal 3=düşük
    baslangic       = Column(DateTime(timezone=True))
    bitis           = Column(DateTime(timezone=True))
    notlar          = Column(Text)
    qr_data         = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    firma           = relationship("Firma")
    recete          = relationship("Recete")
    urun            = relationship("Urun")
    asama_kayitlari = relationship("UretimAsama", back_populates="emir", cascade="all,delete", order_by="UretimAsama.sira")
    hammadde_kullanim = relationship("UretimHammadde", back_populates="emir", cascade="all,delete")
    makine_atamalari  = relationship("UretimMakineAtama", back_populates="emir", cascade="all,delete")
    urun_partiler   = relationship("UrunParti", back_populates="uretim_emri")
    yari_mamul_kaydi = relationship("YariMamul", back_populates="uretim_emri")


class UretimAsama(Base):
    __tablename__ = "uretim_asama"

    id          = Column(Integer, primary_key=True)
    emir_id     = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=False)
    sira        = Column(Integer, nullable=False)
    ad          = Column(String(120), nullable=False)
    aciklama    = Column(Text)
    sorumlu_id  = Column(Integer, ForeignKey("kullanicilar.id"), nullable=True)
    baslangic   = Column(DateTime(timezone=True))
    bitis       = Column(DateTime(timezone=True))
    tamamlandi  = Column(Boolean, default=False)
    notlar      = Column(Text)

    emir        = relationship("UretimEmri", back_populates="asama_kayitlari")
    kontroller  = relationship("KaliteKontrol", back_populates="asama", cascade="all,delete")


class KaliteKontrol(Base):
    __tablename__ = "kalite_kontroller"

    id           = Column(Integer, primary_key=True)
    asama_id     = Column(Integer, ForeignKey("uretim_asama.id"), nullable=False)
    parametre    = Column(String(100), nullable=False)
    hedef_deger  = Column(String(80))
    olculen      = Column(String(80))
    birim        = Column(String(20))
    gecti_mi     = Column(Boolean, nullable=True)
    olcum_tarihi = Column(DateTime(timezone=True), server_default=func.now())
    yapan_id     = Column(Integer, ForeignKey("kullanicilar.id"))
    notlar       = Column(Text)

    asama        = relationship("UretimAsama", primaryjoin="KaliteKontrol.asama_id==UretimAsama.id", back_populates="kontroller")


class UretimHammadde(Base):
    """FIFO ile çekilen hammadde kaydı."""
    __tablename__ = "uretim_hammaddeler"

    id           = Column(Integer, primary_key=True)
    emir_id      = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=False)
    lot_id       = Column(Integer, ForeignKey("hammadde_lotlar.id"), nullable=False)
    fifo_sira    = Column(Integer)
    kullanilan   = Column(Numeric(14,3), nullable=False)
    tarih        = Column(DateTime(timezone=True), server_default=func.now())
    yapan_id     = Column(Integer, ForeignKey("kullanicilar.id"))

    emir         = relationship("UretimEmri", back_populates="hammadde_kullanim")
    lot          = relationship("HammaddeLot")


class UretimMakineAtama(Base):
    """Üretim emrinde kullanılan makineler."""
    __tablename__ = "uretim_makine_atama"

    id          = Column(Integer, primary_key=True)
    emir_id     = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=False)
    makine_id   = Column(Integer, ForeignKey("makineler.id"), nullable=False)
    baslangic   = Column(DateTime(timezone=True))
    bitis       = Column(DateTime(timezone=True))
    notlar      = Column(Text)

    emir        = relationship("UretimEmri", primaryjoin="UretimMakineAtama.emir_id==UretimEmri.id", back_populates="makine_atamalari")
    makine      = relationship("Makine", back_populates="uretim_atamalari")


class UrunParti(Base):
    """Üretimden çıkan nihai ürün partisi."""
    __tablename__ = "urun_partiler"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    urun_id         = Column(Integer, ForeignKey("urunler.id"), nullable=False)
    uretim_emri_id  = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=False)

    parti_no        = Column(String(80), nullable=False, unique=True)
    barkod          = Column(String(60))
    uretim_miktari  = Column(Numeric(14,3), nullable=False)
    kalan_miktar    = Column(Numeric(14,3), nullable=False)
    birim           = Column(String(30), default="kg")

    uretim_tarihi   = Column(DateTime(timezone=True))
    son_kullanma    = Column(DateTime(timezone=True))
    depo_id         = Column(Integer, ForeignKey("depolar.id"), nullable=True)
    qr_data         = Column(Text)
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    urun            = relationship("Urun")
    uretim_emri     = relationship("UretimEmri", back_populates="urun_partiler")


# ═══════════════════════════════════════════════════════════
#  FAZ 3 — KALİTE/HACCP, SATIŞ/SEVKİYAT, ŞİKAYET/RECALL
# ═══════════════════════════════════════════════════════════

class CCPKategori(str, enum.Enum):
    fiziksel   = "fiziksel"
    kimyasal   = "kimyasal"
    biyolojik  = "biyolojik"
    alerjen    = "alerjen"

class CCPDurum(str, enum.Enum):
    uygun      = "uygun"
    sapma      = "sapma"
    kritik     = "kritik"

class TemizlikDurum(str, enum.Enum):
    planlandı  = "planlandı"
    tamamlandı = "tamamlandı"
    atlandi    = "atlandi"

class SiparisDurum(str, enum.Enum):
    taslak     = "taslak"
    onaylı     = "onaylı"
    hazirlaniyor = "hazirlaniyor"
    sevkedildi = "sevkedildi"
    teslim     = "teslim"
    iptal      = "iptal"

class SikayetDurum(str, enum.Enum):
    acik       = "acik"
    inceleme   = "inceleme"
    recall     = "recall"
    kapatildi  = "kapatildi"

class SikayetOncelik(str, enum.Enum):
    dusuk  = "dusuk"
    orta   = "orta"
    yuksek = "yuksek"
    kritik = "kritik"


# ─── HACCP / CCP NOKTALARI ───────────────────────────────

class CCPTanim(Base):
    """Kritik Kontrol Noktası tanımı — bir kez kurulur, üretimlerde kullanılır."""
    __tablename__ = "ccp_tanimlar"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad              = Column(String(150), nullable=False)
    kategori        = Column(SAEnum(CCPKategori), nullable=False)
    aciklama        = Column(Text)
    kritik_limit_min = Column(Numeric(10,3))
    kritik_limit_max = Column(Numeric(10,3))
    hedef_deger     = Column(String(80))
    birim           = Column(String(30))
    olcum_yontemi   = Column(String(200))
    duzeltici_eylem = Column(Text)    # limit aşılırsa ne yapılacak
    sorumlu_unvan   = Column(String(100))
    aktif           = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    firma           = relationship("Firma")
    olcumler        = relationship("CCPOlcum", back_populates="ccp_tanim")


class CCPOlcum(Base):
    """Üretim sırasında CCP ölçüm kaydı."""
    __tablename__ = "ccp_olcumler"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ccp_tanim_id    = Column(Integer, ForeignKey("ccp_tanimlar.id"), nullable=False)
    uretim_emri_id  = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=True)
    uretim_asama_id = Column(Integer, ForeignKey("uretim_asama.id"), nullable=True)

    olculen_deger   = Column(Numeric(10,3), nullable=False)
    birim           = Column(String(30))
    durum           = Column(SAEnum(CCPDurum), nullable=False)
    sapma_aciklama  = Column(Text)
    duzeltici_yapildi = Column(Boolean, default=False)
    duzeltici_not   = Column(Text)
    olcum_tarihi    = Column(DateTime(timezone=True), server_default=func.now())
    yapan_id        = Column(Integer, ForeignKey("kullanicilar.id"))

    ccp_tanim       = relationship("CCPTanim", back_populates="olcumler")
    firma           = relationship("Firma")


# ─── TEMİZLİK & HİJYEN ───────────────────────────────────

class TemizlikPlan(Base):
    """Hangi ekipman/alan ne sıklıkta temizlenecek."""
    __tablename__ = "temizlik_planlar"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad              = Column(String(150), nullable=False)
    alan            = Column(String(150))      # Üretim hattı, Soğuk oda, Mikser...
    yontem          = Column(Text)
    kullanilan_kimyasal = Column(String(200))
    siklık          = Column(String(50))       # Günlük, Haftalık, Aylık
    tahmini_sure    = Column(Integer)          # dakika
    sorumlu_unvan   = Column(String(100))
    aktif           = Column(Boolean, default=True)

    firma           = relationship("Firma")
    kayitlar        = relationship("TemizlikKayit", back_populates="plan")


class TemizlikKayit(Base):
    """Gerçekleştirilen temizlik kaydı."""
    __tablename__ = "temizlik_kayitlar"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    plan_id         = Column(Integer, ForeignKey("temizlik_planlar.id"), nullable=True)
    alan            = Column(String(150))
    durum           = Column(SAEnum(TemizlikDurum), default=TemizlikDurum.tamamlandı)
    baslangic       = Column(DateTime(timezone=True))
    bitis           = Column(DateTime(timezone=True))
    yapan_id        = Column(Integer, ForeignKey("kullanicilar.id"))
    denetleyen_id   = Column(Integer, ForeignKey("kullanicilar.id"))
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    plan            = relationship("TemizlikPlan", back_populates="kayitlar")
    firma           = relationship("Firma")


# ─── MÜŞTERİ ─────────────────────────────────────────────

class Musteri(Base):
    __tablename__ = "musteriler"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(150), nullable=False)
    kod         = Column(String(30))
    vergi_no    = Column(String(20))
    email       = Column(String(150))
    telefon     = Column(String(30))
    adres       = Column(Text)
    sehir       = Column(String(80))
    aktif       = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    firma       = relationship("Firma")
    siparisler  = relationship("SatisEmri", back_populates="musteri")
    sikayetler  = relationship("Sikayet", back_populates="musteri")


# ─── SATIŞ EMRİ & SEVKİYAT ───────────────────────────────

class SatisEmri(Base):
    __tablename__ = "satis_emirleri"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    musteri_id      = Column(Integer, ForeignKey("musteriler.id"), nullable=False)
    siparis_no      = Column(String(60), nullable=False, unique=True)
    durum           = Column(SAEnum(SiparisDurum), default=SiparisDurum.taslak)
    siparis_tarihi  = Column(DateTime(timezone=True), server_default=func.now())
    istenen_termin  = Column(DateTime(timezone=True))
    sevk_adresi     = Column(Text)
    nakliyeci       = Column(String(100))
    plaka           = Column(String(20))
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    firma           = relationship("Firma")
    musteri         = relationship("Musteri", back_populates="siparisler")
    kalemler        = relationship("SatisKalem", back_populates="siparis", cascade="all,delete")
    sevkiyatlar     = relationship("Sevkiyat", back_populates="siparis")


class SatisKalem(Base):
    __tablename__ = "satis_kalemler"

    id              = Column(Integer, primary_key=True)
    siparis_id      = Column(Integer, ForeignKey("satis_emirleri.id"), nullable=False)
    urun_parti_id   = Column(Integer, ForeignKey("urun_partiler.id"), nullable=True)
    urun_id         = Column(Integer, ForeignKey("urunler.id"), nullable=True)
    aciklama        = Column(String(200))
    miktar          = Column(Numeric(14,3), nullable=False)
    birim           = Column(String(30))
    birim_fiyat     = Column(Numeric(14,4))
    kdv_oran        = Column(Numeric(5,2), default=10)
    toplam          = Column(Numeric(14,2))

    siparis         = relationship("SatisEmri", back_populates="kalemler")
    urun_parti      = relationship("UrunParti")
    urun            = relationship("Urun")


class Sevkiyat(Base):
    __tablename__ = "sevkiyatlar"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    siparis_id      = Column(Integer, ForeignKey("satis_emirleri.id"), nullable=True)
    sevk_no         = Column(String(60), nullable=False, unique=True)
    sevk_tarihi     = Column(DateTime(timezone=True))
    tahmini_teslim  = Column(DateTime(timezone=True))
    gercek_teslim   = Column(DateTime(timezone=True))
    nakliyeci       = Column(String(100))
    plaka           = Column(String(20))
    sofor           = Column(String(100))
    notlar          = Column(Text)
    qr_data         = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    firma           = relationship("Firma")
    siparis         = relationship("SatisEmri", back_populates="sevkiyatlar")
    kalemler        = relationship("SevkiyatKalem", back_populates="sevkiyat", cascade="all,delete")


class SevkiyatKalem(Base):
    __tablename__ = "sevkiyat_kalemler"

    id              = Column(Integer, primary_key=True)
    sevkiyat_id     = Column(Integer, ForeignKey("sevkiyatlar.id"), nullable=False)
    urun_parti_id   = Column(Integer, ForeignKey("urun_partiler.id"), nullable=False)
    miktar          = Column(Numeric(14,3), nullable=False)
    birim           = Column(String(30))

    sevkiyat        = relationship("Sevkiyat", back_populates="kalemler")
    urun_parti      = relationship("UrunParti")


# ─── ŞİKAYET & RECALL ────────────────────────────────────

class Sikayet(Base):
    __tablename__ = "sikayetler"

    id               = Column(Integer, primary_key=True)
    firma_id         = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    musteri_id       = Column(Integer, ForeignKey("musteriler.id"), nullable=True)
    uretim_emri_id   = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=True)
    urun_parti_id    = Column(Integer, ForeignKey("urun_partiler.id"), nullable=True)
    lot_id           = Column(Integer, ForeignKey("hammadde_lotlar.id"), nullable=True)

    sikayet_no       = Column(String(60), nullable=False, unique=True)
    baslik           = Column(String(200), nullable=False)
    aciklama         = Column(Text, nullable=False)
    oncelik          = Column(SAEnum(SikayetOncelik), default=SikayetOncelik.orta)
    durum            = Column(SAEnum(SikayetDurum), default=SikayetDurum.acik)
    is_recall        = Column(Boolean, default=False)
    etkilenen_miktar = Column(Numeric(14,3))
    geri_cagrilan    = Column(Numeric(14,3), default=0)
    kok_neden        = Column(Text)
    duzeltici_eylem  = Column(Text)
    kapanis_tarihi   = Column(DateTime(timezone=True))
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    created_by       = Column(Integer, ForeignKey("kullanicilar.id"))

    firma            = relationship("Firma")
    musteri          = relationship("Musteri", back_populates="sikayetler")
    uretim_emri      = relationship("UretimEmri")
    urun_parti       = relationship("UrunParti")
    lot              = relationship("HammaddeLot")
    yorumlar         = relationship("SikayetYorum", back_populates="sikayet", cascade="all,delete")


class SikayetYorum(Base):
    __tablename__ = "sikayet_yorumlar"

    id           = Column(Integer, primary_key=True)
    sikayet_id   = Column(Integer, ForeignKey("sikayetler.id"), nullable=False)
    kullanici_id = Column(Integer, ForeignKey("kullanicilar.id"))
    metin        = Column(Text, nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    sikayet      = relationship("Sikayet", primaryjoin="SikayetYorum.sikayet_id==Sikayet.id", back_populates="yorumlar")


# ═══════════════════════════════════════════════════════════
#  FAZ 4 — VARDİYA, KALİBRASYON, ANALİZ
# ═══════════════════════════════════════════════════════════

class VardiyaTip(str, enum.Enum):
    sabah   = "sabah"    # 06:00–14:00
    oglen   = "oglen"    # 14:00–22:00
    gece    = "gece"     # 22:00–06:00
    tam_gun = "tam_gun"

class KalibrasyonDurum(str, enum.Enum):
    gecerli  = "gecerli"
    suresi_dolmus = "suresi_dolmus"
    beklemede = "beklemede"


# ─── VARDİYA ─────────────────────────────────────────────

class Vardiya(Base):
    __tablename__ = "vardiyalar"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    tarih           = Column(DateTime(timezone=True), nullable=False)
    tip             = Column(SAEnum(VardiyaTip), default=VardiyaTip.sabah)
    sorumlu_id      = Column(Integer, ForeignKey("kullanicilar.id"), nullable=True)
    baslangic       = Column(DateTime(timezone=True))
    bitis           = Column(DateTime(timezone=True))
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    firma           = relationship("Firma")
    personel        = relationship("VardiyaPersonel", back_populates="vardiya", cascade="all,delete")
    uretim_emirleri_rel = relationship("VardiyaUretim", back_populates="vardiya", cascade="all,delete")


class VardiyaPersonel(Base):
    __tablename__ = "vardiya_personel"

    id          = Column(Integer, primary_key=True)
    vardiya_id  = Column(Integer, ForeignKey("vardiyalar.id"), nullable=False)
    kullanici_id = Column(Integer, ForeignKey("kullanicilar.id"), nullable=False)
    gorev       = Column(String(100))
    giris       = Column(DateTime(timezone=True))
    cikis       = Column(DateTime(timezone=True))

    vardiya     = relationship("Vardiya", back_populates="personel")


class VardiyaUretim(Base):
    __tablename__ = "vardiya_uretim"

    id              = Column(Integer, primary_key=True)
    vardiya_id      = Column(Integer, ForeignKey("vardiyalar.id"), nullable=False)
    uretim_emri_id  = Column(Integer, ForeignKey("uretim_emirleri.id"), nullable=False)

    vardiya         = relationship("Vardiya", back_populates="uretim_emirleri_rel")


# ─── EKİPMAN KALİBRASYON ────────────────────────────────

class KalibrasyonKaydi(Base):
    __tablename__ = "kalibrasyon_kayitlari"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    makine_id       = Column(Integer, ForeignKey("makineler.id"), nullable=False)
    kalibrasyon_no  = Column(String(60))
    yapan_kurum     = Column(String(150))
    tarih           = Column(DateTime(timezone=True), nullable=False)
    gecerlilik_bitis = Column(DateTime(timezone=True), nullable=False)
    durum           = Column(SAEnum(KalibrasyonDurum), default=KalibrasyonDurum.gecerli)
    sonuc           = Column(String(200))
    belge_no        = Column(String(100))
    maliyet         = Column(Numeric(10,2))
    notlar          = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    created_by      = Column(Integer, ForeignKey("kullanicilar.id"))

    firma           = relationship("Firma")
    makine          = relationship("Makine", primaryjoin="KalibrasyonKaydi.makine_id==Makine.id")


# ─── STOK TAHMİN & ANALİZ ────────────────────────────────

class StokTuketimKaydi(Base):
    """
    Günlük tüketim kaydı — tahmin modeli için girdi.
    FIFO çekimlerinden otomatik doldurulur.
    """
    __tablename__ = "stok_tuketim_kayitlari"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    hammadde_id     = Column(Integer, ForeignKey("hammaddeler.id"), nullable=False)
    tarih           = Column(DateTime(timezone=True), nullable=False)
    tuketilen       = Column(Numeric(14,3), nullable=False)
    birim           = Column(String(20))

    firma           = relationship("Firma")
    hammadde        = relationship("Hammadde")


# ═══════════════════════════════════════════════════════════
#  FAZ 5 — ETİKET, BİLDİRİM, SİSTEM AYARLARI, API LOG
# ═══════════════════════════════════════════════════════════

class EtiketSablon(Base):
    """Baskı etiketi şablonu tanımı."""
    __tablename__ = "etiket_sablonlar"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(100), nullable=False)
    tip         = Column(String(30), nullable=False)  # lot / urun_parti / numune / sevkiyat
    genislik_mm = Column(Integer, default=100)
    yukseklik_mm = Column(Integer, default=60)
    icerik      = Column(Text)   # JSON field listesi
    aktif       = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    firma       = relationship("Firma")


class BildirimKaydi(Base):
    """Sistem bildirimleri — SKT, kritik stok, numune, sapma vb."""
    __tablename__ = "bildirim_kayitlari"

    id              = Column(Integer, primary_key=True)
    firma_id        = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    kullanici_id    = Column(Integer, ForeignKey("kullanicilar.id"), nullable=True)
    tip             = Column(String(50), nullable=False)  # skt_uyari, kritik_stok, numune, ccp_sapma, recall
    baslik          = Column(String(200), nullable=False)
    mesaj           = Column(Text)
    okundu          = Column(Boolean, default=False)
    ilgili_tip      = Column(String(30))    # lot / parti / sikayet vb.
    ilgili_id       = Column(Integer)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    firma           = relationship("Firma")


class SistemAyar(Base):
    """Firma bazlı sistem ayarları — key/value."""
    __tablename__ = "sistem_ayarlar"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    anahtar     = Column(String(80), nullable=False)
    deger       = Column(Text)
    aciklama    = Column(String(200))

    __table_args__ = (UniqueConstraint("firma_id", "anahtar", name="uq_firma_ayar"),)

    firma       = relationship("Firma")


class ApiAnahtari(Base):
    """Harici entegrasyon için API anahtarları."""
    __tablename__ = "api_anahtarlari"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=False)
    ad          = Column(String(100), nullable=False)
    anahtar     = Column(String(64), unique=True, nullable=False)
    izinler     = Column(String(500), default="read")  # read,write,admin
    aktif       = Column(Boolean, default=True)
    son_kullanim = Column(DateTime(timezone=True))
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    created_by  = Column(Integer, ForeignKey("kullanicilar.id"))

    firma       = relationship("Firma")


class DenetimIzi(Base):
    """Kim ne zaman ne yaptı — tam audit log."""
    __tablename__ = "denetim_izi"

    id          = Column(Integer, primary_key=True)
    firma_id    = Column(Integer, ForeignKey("firmalar.id"), nullable=True)
    kullanici_id = Column(Integer, ForeignKey("kullanicilar.id"), nullable=True)
    islem       = Column(String(50), nullable=False)   # CREATE, UPDATE, DELETE, LOGIN
    tablo       = Column(String(60))
    kayit_id    = Column(Integer)
    eski_deger  = Column(Text)
    yeni_deger  = Column(Text)
    ip_adresi   = Column(String(45))
    tarih       = Column(DateTime(timezone=True), server_default=func.now())

    firma       = relationship("Firma")
