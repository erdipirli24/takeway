# TraceWay — Gıda İzlenebilirlik Platformu

## Kurulum (Railway)

1. GitHub'a push et
2. Railway → New Project → GitHub repo seç
3. Environment Variables ekle:
   - `DATABASE_URL` → PostgreSQL servisinden otomatik inject edilir
   - `SECRET_KEY` → Güçlü rastgele string
   - `ADMIN_EMAIL` / `ADMIN_PASSWORD` → İlk admin hesabı
4. Deploy — tablolar ve demo veriler otomatik oluşur

## Demo Hesaplar

| Hesap | E-posta | Şifre |
|---|---|---|
| Merkez Admin | demo@elfiga.com | Demo1234! |
| Şube Müdürü | kadikoy@elfiga.com | Demo1234! |
| Gıda Mühendisi | ayse@elfiga.com | Demo1234! |

## Faz Özeti

| Faz | Kapsam |
|---|---|
| 1 | Firma/şube, yetki matrisi, FIFO depo, hammadde, numune |
| 2 | Reçete (3 tip), karışım modu, makine, üretim emri, parti |
| 3 | Kalite/HACCP, satış/sevkiyat, şikayet/recall, raporlar |
| 4 | Allerjen matrisi, stok tahmin, raf ömrü, kalibrasyon, mobil |
| 5 | Etiket baskı, bildirim merkezi, API, performans, denetim izi |

## REST API

```
GET /sistem/api/v1/stok?api_key=XXX
GET /sistem/api/v1/izlenebilirlik/{parti_no}?api_key=XXX
```
