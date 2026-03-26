"""
Merkezi Jinja2 templates nesnesi.
Tüm router'lar buradan import eder — filtreler tek yerde tanımlanır.
"""
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


def fmt_sayi(val):
    """Decimal/float düzgün göster: 40.000 → 40, 1.500 → 1.5"""
    try:
        f = float(val or 0)
        if f == int(f):
            return str(int(f))
        return f"{f:.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(val) if val is not None else "0"


templates.env.filters["fmt"] = fmt_sayi
