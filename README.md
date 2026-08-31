<div align="center">

# 🎯 AVCI DRONE — YER KONTROL İSTASYONU

### TEKNOFEST 2026 · Savaşan İHA Avcı Drone Yarışması
**Takım: hamidiye**

*Tek araç · tek arayüz · GPS + görsel hibrit güdüm*

</div>

---

## Bu nedir

Bir **avcı drone**yu yarışma sunucusundan gelen hedef konumuna göre otonom
uçuran yer kontrol istasyonu. Hedef İHA yarışma komitesinin kontrolündedir —
biz uçurmuyoruz. Konumu bize sunucudan **kasten bozulmuş** olarak gelir
(gürültü, ani sıçrama, veri kesintisi, gecikme) ve bir Kalman süzgeciyle
temizlenir.

```
    yarışma sunucusu                    AVCI DRONE
    (hedef GPS, bozuk)                       ▲
            │                                │ ELRS 2.4 GHz
            │ HTTP/JSON 1.8 Hz               │
            ▼                                │
    ┌───────────────────────────────────────────────┐
    │            BU YAZILIM  (localhost:8810)        │
    │                                                │
    │  hedef ──► yaş kapısı ──► GNSS süzgeci ──┐     │
    │                                          ▼     │
    │  kamera ─► YOLO ─► görsel güdüm ──► HAKEM ──►  │
    │                                          ▲     │
    │  kumanda ──────────────────────────────┘       │
    │  panel   ──────────────────────────────┘       │
    └───────────────────────────────────────────────┘
```

**Hakem** (`gercek/komut.py`) tek çıkış kapısıdır: pilot mu otonom mu komut
veriyor, ona karar verir. Otonom için **dört şart birden** gerekir.

---

## ⚡ Hızlı başlangıç

```bash
# 1 · sunucuyu sına (uçmadan ÖNCE)
python3 araclar/sunucu_testi.py

# 2 · backend (Terminal 1, açık kalır)
./skydagger/baslat_backend.sh

# 3 · yer kontrolü (Terminal 2, açık kalır)
./baslat.sh
```
→ **http://localhost:8810**

---

# 1 · YARIŞMA GÜNÜ — SIFIRDAN

## 1.0 · Donanımı tak — sıra önemli

| # | ne | not |
|---|---|---|
| 1 | **Skydagger ESP32** (ELRS köprüsü) → USB | ⛔ 2S pilini **HENÜZ TAKMA** |
| 2 | **FPV yakalama kartı** → USB | video vericisi açık olsun |
| 3 | **Kumanda** → USB, aç | EdgeTX: **USB Mode = Joystick** |
| 4 | **Ethernet** → yarışma ağı | doküman §2 |
| 5 | **Drone pili** | alan boş, kimse yakında değil |

**Doğrula:**
```bash
ls -l /dev/serial/by-id/ ; ls /dev/video* ; ls /dev/input/js*
```

| görmen gereken | nedir |
|---|---|
| `usb-Silicon_Labs_CP2102_...` | **ESP32** (drone RC köprüsü) |
| `/dev/video2` | yakalama kartı *(`video0` dahili webcam, karıştırma)* |
| `/dev/input/js0` | kumanda |

> ⛔ `ttyUSB0/1` numaraları takma sırasına göre **değişir**. Komutlarda daima
> `by-id` yolu kullanılır — o, çipin seri numarasına bağlıdır ve sabittir.

## 1.1 · Sunucu bilgileri

`baslat.sh` içinde hazır:

```bash
export DOW_SUNUCU="http://10.0.0.1:5000"   # ⚠ PORT teyit edilmedi
export DOW_SUNUCU_KADI="hamidiye"
export DOW_SUNUCU_SIFRE="Z8vN1cR5tY"
export DOW_TAKIM_NO="0"                    # ⚠ hakemler numara bildirmedi
```

**Sahada hakemden öğren:**
1. **Port** — 5000 varsayıldı, bağlantı hatası alırsan ilk şüpheli bu
2. **Takım numarası** — bildirilmediyse 0 kalabilir; sunucu testi paketi
   kabul ediyorsa sorun yoktur
3. **Kilitlenme uç adresi** — aşağıdaki açık soruya bak

## 1.2 · Sunucuyu sına — ⭐ uçmadan önce

```bash
cd ~/projects/yarisma
python3 araclar/sunucu_testi.py
```

Sırayla şunları kanıtlar: adres ulaşılabilir mi · kimlik geçiyor mu · sunucu
saati alınıyor mu · **telemetri paketimiz kabul ediliyor mu** · yanıtta hedef
verisi geliyor mu · 2 Hz sınırını aşıyor muyuz.

```
  [1] OTURUM AÇMA…                    ✔ giriş başarılı
  [2] SUNUCU SAATİ…                   ✔ {'saat': 11, …}
  [3] TELEMETRİ + HEDEF (20 s)…
      sn   gönderilen  hata  hedef_paket  yaş(s)   hedef konum
         2          3     0            3    0.75   41.000775, 29.000700
  ✔ SUNUCU HAZIR — telemetri gidiyor, hedef verisi geliyor.
```

⛔ **Bu yeşil olmadan uçma.**

## 1.3 · Skydagger backend — Terminal 1

```bash
cd ~/projects/yarisma/skydagger
./baslat_backend.sh
```

Konsola **sırayla**:

| komut | ne olmalı |
|---|---|
| `/connect /dev/serial/by-id/usb-Silicon_Labs_CP2102_..._0001-if00-port0` | ESP32 bulunur |
| `RC_ENABLE` | **şimdi modüle 2S pili tak** → ışık **MAVİ** |
| `STOP` | ışık **SARI** |
| `EXTERNAL` | yazılım devralır |

> ⛔ `/connect`'i yalnız başına yazma — portu **elle** ver.

## 1.4 · Yer kontrolü — Terminal 2

```bash
cd ~/projects/yarisma
./baslat.sh
```

Açılışta **gözünle doğrula**:
```
SUNUCU  : http://10.0.0.1:5000   takım 0   kadı hamidiye
GÖNDERİM: 1.8 Hz  (⛔ doküman sınırı 2 Hz)
GNSS    : süzgeç AÇIK  R=200 cm  dt=0.55 s
HEDEF   : YALNIZ yarışma sunucusu yanıtı (UDP kapalı)
KAMERA  : /dev/video2  640x480      ← çözünürlük uyarısı ÇIKMAMALI
DEDEKTÖR: yüklendi
ÇEVİRİCİ: MODEL=aci  ACI_MAX=60  Y_ISARET=+1.0
```

**Tarayıcı → http://localhost:8810**

1. İlk 5 saniye `SAFE PENCERESİ` yazar — **modülün MAVİ ışığını o an doğrula**
2. **KÖKEN KUR** — drone yerde ve hareketsizken, **uydu ≥ 10** iken
3. Ön uçuş listesi **8/8 yeşil**
4. `SUNUCU` rozetinde gönderim sayacı **artıyor**

> **Köken nedir:** GPS derece verir, güdüm metre ile çalışır. Köken "şu noktayı
> sıfır kabul et" demektir. Kurulmadan bütün metre hesabı 0 çıkar. Her yeniden
> başlatmada tekrar kurulur.

---

# 2 · GÖREVİN İCRASI

| an | ne yaparsın | panelde neye bakarsın |
|---|---|---|
| Hedef havalandı | — | `GPS akışı: VAR, yaş < 1 s` |
| **Kalkış** | **ARM (BASILI TUT)** + **MANUEL** → elle 30-50 m | araç dengede |
| **Takip** | **OTONOM** | `kaynak: OTONOM` · `güdüm: ISTASYON` |
| Yaklaşma | izle | `kuzey/doğu ⟶ uzaklık` **AZALIYOR** |
| Görsel temas | otomatik | `güdüm: GÖRSEL` · FPV'de kutu |
| Kilit | otomatik | `kilit` sayacı · sunucuya paket gider |

⛔ **Otonoma yerden geçme.** Kalkış fazı kapalıdır (`DOW_KALKIS_ALT=0`);
OTONOM'a basınca araç **hemen hedefe yönelir**.

### Otonom için DÖRT ŞART birden
```
① panel OTONOM istiyor        ② pilot izin veriyor
③ güdüm taze setpoint üretiyor ④ kumandayla bağ teslim süresi içinde
```
Biri düşerse otonom **o tikte** düşer ve komut çubuklara geçer.

### 🚨 Çıkış — üç yol, ezberle

| yol | ne olur |
|---|---|
| **Kumanda çubuğuna dokun** | anında MANUEL, **mandallı** — kendiliğinden dönmez |
| Panelde **MANUEL** | otonom düşer |
| **⛔ FAILSAFE — DİKEY İNİŞ** | görevi keser, olduğu yerde sabit hızla iner |

**Dikey iniş** uçuş kartının kendi **ALT HOLD + POS HOLD** kiplerini açar
(kanal 6 ve 8 → 1899 µs): 3 saniye asılı kalır, sonra sabit hızda alçalır,
konumu GPS ile tutar. ⛔ **Kendiliğinden disarm etmez** — yere değince sen
disarm edersin.

Son çare olarak panelde küçük bir düğme daha var: **RC paketini kes** →
uçuş kartının kendi `failsafe_procedure = AUTO-LAND`'i devreye girer.

---

# 3 · KAPATMA — sıra önemli

Backend konsolunda:
```
EXTERNAL STOP
/disconnect
```
⛔ `/disconnect` atlanırsa ESP32 kötü boot moduna düşebilir.

Sonra modül pilini → drone pilini → USB'leri çek. Ardından:
```bash
./baslat.sh --kapat && ./skydagger/baslat_backend.sh --kapat
ss -lntu | grep -E ":8765|:8766|:8767|:8810"     # boş çıkmalı
```

> ⚠ **Fişi çekmek yazılımı kapatmaz.** Süreçler ayakta kalır ve portları tutar.

---

# 4 · HABERLEŞME (Doküman 2026 · birebir)

| uç | ne yapar |
|---|---|
| `POST /api/giris` | `{"kadi","sifre"}` — oturum |
| `GET /api/sunucusaati` | sunucu saati |
| `POST /api/telemetri_gonder` | telemetrimiz → **yanıtta hedef İHA verileri** |

**Gönderdiğimiz (§7.1)** — 14 alan, `drone_yki._telemetri()`:

`takim_no` · `enlem` · `boylam` · `irtifa` · `dikilme` · `yonelme` · `yatis` ·
`hiz` · `mod` · `kilitlenme` · `hedef_x_merkezi` · `hedef_y_merkezi` ·
`hedef_genislik` · `hedef_yukseklik`

> `mod` alanı **hakemin gerçekte ne gönderdiğini** söyler, panelde ne seçili
> olduğunu değil. Yapmadığımız bir şeyi beyan etmeyiz.

**Aldığımız (§7.2):** `sunucu_saati` + `hedef_iha_verileri[]`
(`takim_no` · `enlem` · `boylam` · `irtifa_ev` · `hiz` · `saat_farki`)

### ⛔⛔ Hız sınırı — dokümanın cezalı kuralı

> *"En az 1 Hz gönderilmelidir. **2 Hz üzerinde gönderilen paketler 400 durum
> kodu ile 3 hata kodu ile cevaplanır.**"*

Kod **1.8 Hz**'de sınırlıdır ve ikinci bir güvence olarak 0.5 s'den sık
göndermeyi reddeder.

### ⚠ Hedef tazeleme hızı = bizim gönderim hızımız

Hedef verisi ayrı bir akışta değil, telemetri **yanıtında** gelir. Ölçüldü
(sahte sunucuya karşı): `gönderilen 1.50 Hz → hedef paket 1.38 Hz`.

**Pratik sonucu:** paketler arası ~0.55 s. 20 m/s giden bir hedef bu sürede
**11 metre** yol alır. Süzgecin ölü hesabı ve 1 saniyelik ileri taşıması
(lead) tam bunu kapatmak içindir.

### ⛔ AÇIK SORU — hakemden teyit et

Doküman **§8** kilitlenme bilgisi göndermeyi **zorunlu** kılıyor, ama **§4**
API listesinde o uç **YOK**. Kod `/api/kilitlenme_bilgisi` varsayıyor.
Yanlışsa kilit paketleri 404 alır ve **puan kaybedilir.**

---

# 5 · GNSS SÜZGECİ — bozuk hedef GPS'i

Hedef konumu kasten bozulmuş gelir. `gercek/gnss_filtre.py` temizler.

| bileşen | ne yapar |
|---|---|
| **CT-EKF** | hedefin sabit dönüş hızıyla döndüğünü varsayar → **manevrayı öngörür**. Düz uçan bir model viraja gireni sürekli geriden takip ederdi |
| **Mahalanobis kapısı** | jammer sıçramasını *istatistiksel olarak* reddeder. Ham metre eşiğinden üstündür: filtre eminken dar, belirsizken geniş davranır |
| **Kaçış** | kapı üst üste reddederse belirsizlik şişirilir → jammer yeni rejime geçerse 2-3 s'de yeniden kilitlenir |
| **Ölü hesap** | kesintide son hız+dönüşle ileri gider, `DOW_GNSS_DR_MAKS` ile sınırlı |
| **Lead** | çıktı `DOW_GNSS_TELAFI` kadar ileri taşınır (GPS gecikmesi) |

⛔ Süzgeç **yerel metrik çerçevede** çalışır (enlem/boylamda değil, çünkü
derece cinsinden mesafeler enlemle ölçeklenir ve Kalman'ın doğrusal
varsayımlarını bozar) ve **SANTİMETRE** ister — çevrimi sarmalayıcı yapar.

### ⭐ En önemli ayar: `DOW_GNSS_R`

Ölçüm gürültüsü (cm). **Gerçek bozulma büyüklüğüne eşlenmeli.** Ölçüldü:

| bozulma | R | reddedilen | iyileşme |
|---|---|---|---|
| 2 m | **200** | 1/200 | **%64** |
| 2 m | 50 *(ayarsız)* | **150/200** | çöküyor |
| 2 m | 200, lead kapalı | 1/200 | %11 |
| 5 m | 500 | 1/200 | %15 |

**Sahada ayarı:** panelde `gnss.reddedilen` sayacı hızla artıyorsa **R
küçüktür** → 200 → 400 → 800 diye yükselt.

---

# 6 · YERDE KANITLANMIŞ OLANLAR

| ne | nasıl ölçüldü |
|---|---|
| **`Y_ISARET = +1.0` doğru** | `yon_testi.py --mod cevir` · 37 örnek, 5 burun yönü · toplanma **H0 0.992** vs H1 0.156 · hedefe sapma **+0.4°** vs −92.9° · sapma medyanı **1.0°** |
| Çubuklar hedefi takip ediyor | `cubuk_izle.py` · 55-59 m'de **69 uyumlu / 0 uyumsuz** |
| Manuel kontrol | kumanda + panel, çubuk eşlemesi doğru |
| ARM iki kaynaktan | panel (basılı tut) + kumanda anahtarı |
| Pilot devralma **mandallı** | çubuğa dokununca `sebep=pilot_devraldi`, kendiliğinden dönmez |
| Failsafe dikey iniş | tezgâhta: kanal 6/8 → 1899 µs, TUT→IN, sabit hız |
| GNSS süzgeci | sentetik: ham 21.3 m → süzülmüş **7.8 m** |
| Sunucu haberleşmesi | sahte sunucuya karşı uçtan uca ✔ |

> `Y_ISARET` sorusu aylarca *"kesin kanıtı ilk otonom uçuştur"* diye açık
> durdu. **Yerde, pervanesiz, DISARM hâlde kapandı.**

# 7 · AÇIK RİSKLER

| risk | durum |
|---|---|
| Dikey iniş **hiç uçmadı** | ilk kullanımı güvenli irtifada, pilot kumandada |
| Alçalma hızı ölçülmedi | `DOW_INIS_CUBUK=-0.35` başlangıç; ölç, ayarla |
| `MENZIL_C` türetme | yalnız **görsel** fazı etkiler, GPS fazını değil |
| Kilitlenme uç adresi | doküman §4'te yok — **hakemden teyit** |
| Sunucu portu | 5000 varsayıldı — **hakemden teyit** |
| Takım numarası | bildirilmedi — sunucu testi kabul ediyorsa sorun yok |

---

# 8 · ARAÇLAR

```bash
python3 araclar/sunucu_testi.py          # ⭐ sunucu: giriş, paket, hedef, hız
python3 gercek/hedef_testi.py            # hedef akışı (Hz, yaş, reddedilen)
python3 gercek/kamera_ayari.py --tara    # yakalama kartını bul
python3 gercek/tespit_izle.py            # dedektör güveni, canlı
python3 gercek/cubuk_izle.py             # güdümün istediği yön, canlı
python3 gercek/yon_testi.py --mod cevir  # yön işareti (yerde, pervanesiz)
python3 gercek/menzil_olc.py --mesafe 10 # MENZIL_C ölç
python3 -m pytest tests/ -q              # 101 bekçi
```

# 9 · YAPI

```
yarisma/
├── baslat.sh                TEK komut · bütün ayarlar burada
├── drone_yki.py             ana döngü, panel, sunucu, kayıt
├── gercek/
│   ├── komut.py             ⭐ HAKEM — pilot mu otonom mu (dört şart)
│   ├── gnss_filtre.py       ⭐ bozuk hedef GPS'ini temizler
│   ├── sunucu.py            yarışma sunucusu istemcisi
│   ├── hedef.py             hedef paketi + yaş kapısı
│   ├── baglanti.py          araç telemetrisi, yerel çerçeve
│   ├── panel.py             yer kontrol arayüzü (8810)
│   ├── dikey_inis.py        failsafe: ALT HOLD + POS HOLD
│   ├── skydagger.py         ELRS köprüsü (RC_US)
│   └── …
├── dow/                     güdüm çekirdeği (GPS + görsel + çevirici)
├── skydagger/               ELRS backend
├── modeller/tayarti_v1.pt   YOLO — gerçek görüntüyle eğitildi
└── tests/                   101 bekçi
```

# 10 · KURULUM (yeni makinede)

```bash
git clone https://github.com/kayranecatikara/yarisma ~/projects/yarisma
cd ~/projects/yarisma
pip install -r requirements.txt
./skydagger/kur.sh
```

---

<div align="center">

### 🛡️ DEĞİŞMEZ EMNİYET KURALLARI

**ARM daima insandan gelir** — güdümün arm kanalına erişimi yoktur

**Disarm asla emniyet tedbiri olarak gönderilmez** — havada disarm = serbest düşüş

**Pilot her zaman son sözü söyler** — çubuğa dokunuş otonomu mandallı olarak düşürür

**Pervaneler, yerdeki her denemede çıkarılır**

</div>
