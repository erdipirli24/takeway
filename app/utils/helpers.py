import qrcode, base64
from io import BytesIO
from datetime import datetime


def qr_olustur(data: str) -> str:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0d1117", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def ic_parti_no(firma_id: int, hammadde_id: int, sira: int) -> str:
    yil = datetime.now().strftime("%y")
    return f"TW-{firma_id:02d}-HM{hammadde_id:03d}-{yil}-{sira:04d}"


def numune_no(firma_id: int, sira: int) -> str:
    gun = datetime.now().strftime("%y%m%d")
    return f"NM-{firma_id:02d}-{gun}-{sira:04d}"


def firma_kodu_olustur(parent_kod: str, sube_sira: int) -> str:
    """Şube kodu: parent=2 → 2-1, 2-2"""
    return f"{parent_kod}-{sube_sira}"
