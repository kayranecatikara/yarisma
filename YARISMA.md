# YARIŞMA GÜNÜ — çalıştırma komutları

Hedef verisi **gerçek yarışma sunucusundan** gelir. Sahte sunucu ve harita
YOK.

> ⭐ Aşağıdaki komutların hepsi **tam yollu** — hangi dizinde olursan ol
> kopyala-yapıştır çalışır. `cd` yapmana gerek yok.

---

## 0 · TEMİZLİK

```bash
for p in $(pgrep -f drone_yki; pgrep -f sahte_sky; pgrep -f sahte_sun); do kill -9 $p; done
ss -ltn | grep -E ":8766|:8810" || echo "portlar bos"
```

`portlar bos` yazmalı.

---

## 1 · AĞ — ethernet kablosunu tak, sonra:

```bash
sudo ~/projects/yarisma/araclar/ag_kur.sh
```

Beklenen son satır: **`AĞ HAZIR.`**
Kurduğu: `enp4s0` → `10.0.0.114/24`, sunucu `10.0.0.10:10001`.

Hakemler farklı adres verirse:
```bash
sudo AG_ADRES=10.0.0.X/24 AG_SUNUCU=10.0.0.Y ~/projects/yarisma/araclar/ag_kur.sh
```

---

## 2 · SUNUCU DOĞRULAMA (araç gerekmez)

```bash
python3 ~/projects/yarisma/araclar/sunucu_testi.py --sure 20
```

Görmen gerekenler: giriş **başarılı** · telemetri **kabul** · hedef verisi
**geliyor** · hız ihlali **0**.

⛔ Burada takılırsan uçma. Adres/port/takım no'yu hakemle teyit et.

---

## 3 · BACKEND (Terminal 1)

```bash
~/projects/yarisma/skydagger/baslat_backend.sh
```

Konsolunda **sırayla**:

```
/connect
RC_ENABLE
            → ŞİMDİ 2S pili tak → ışık MAVİ
STOP
EXTERNAL
```

---

## 4 · YER KONTROL İSTASYONU (Terminal 2)

```bash
~/projects/yarisma/baslat.sh
```

⚠ Kamera `/dev/video2` varsayılan. Farklıysa:
```bash
python3 ~/projects/yarisma/gercek/kamera_ayari.py --tara   # cihazı bul
DOW_KAM_KAYNAK=/dev/videoX ~/projects/yarisma/baslat.sh
```

Açılışta görmen gerekenler:
```
SUNUCU    : http://10.0.0.10:10001   takım 2   kadı hamidiye
SUNUCU    : http://10.0.0.10:10001 — giriş başarılı
DEDEKTÖR  : yüklendi
KAMERA    : /dev/videoX  640x480
ÇEVİRİCİ  : MODEL=aci  ACI_MAX=60  Y_ISARET=+1.0
HEDEF     : YALNIZ yarışma sunucusu yanıtı (UDP kapalı)
```

⛔ **"ÇÖZÜNÜRLÜK UYUŞMAZLIĞI" uyarısı çıkarsa DUR** — `DOW_KAM_W=640 DOW_KAM_H=480` ekle.

---

## 5 · PANEL → `http://127.0.0.1:8810`

Sırayla:

| # | düğme | kontrol |
|---|---|---|
| 1 | **`KÖKEN KUR`** | araç yerde. ⭐ ARM'dan hemen önce **tekrar bas** (GPS irtifası sürükleniyor) |
| 2 | **`OTONOM`** | yalnız kip seçer, görev başlamaz |
| 3 | — | sol pad'de **gazı DİBE çek** → `gaz kanalı` satırı `✔ arm edilebilir` demeli |
| 4 | **`ARM`** | mandal; onay ister. Motorlar döner |
| 5 | **`GÖREVİ BAŞLAT`** | tek tık, onay yok. Araç 3 m/s ile 35 m'ye tırmanır |

**Ön uçuş listesi 8/8 olmalı.**

---

## 6 · GÖREV SIRASINDA İZLE

| alan | olması gereken |
|---|---|
| kip şeridi | `🚀 GÖREV SÜRÜYOR — KALKIS → ISTASYON → GORSEL` |
| `kaynak` | `OTONOM`, `sebep` boş |
| `telemetri yaşı` | gps/duruş **< 0.1 s** |
| `hedef` | `var`, yaş **< 1.5 s** |
| başlık `SUNUCU` | sayı **artıyor** (paket gidiyor) |
| FPV | görüntü akıyor, tespit kutusu çiziliyor |
| `KİLİT x.x/5.0 s` | görsel fazda **doluyor** |

**Faz akışı:** `KALKIS` → `ISTASYON` (GPS) → 10 ardışık tespit → `GORSEL/KILIT`
(kutuyu ekranın %8'inde tutar, kilit biriktirir) → ister sağlanınca
`TERMINAL` (vuruş).

---

## 7 · DURDURMA

| durum | ne bas |
|---|---|
| normal | **`GÖREVİ DURDUR`** |
| kontrolü al | **`MANUEL`** (kumanda o an canlanır) |
| acil | **`FAILSAFE — DİKEY İNİŞ`** |
| son çare | **`son çare: RC paketini kes`** (kart kendi AUTO-LAND yapar) |
| motorları kes | **`DISARM`** (anında, onaysız) |

⛔ **OTONOM'da kumanda güdüme karışmaz.** Durdurmak panelden.

---

## 8 · KAPANIŞ (sırayla)

Backend konsolunda:
```
EXTERNAL STOP
/disconnect          ⛔ ATLAMA — ESP kötü boot moduna düşer
```
→ pili çek → USB'yi çek → Terminal 2'de `Ctrl+C`

Ağı geri almak (isteğe bağlı):
```bash
sudo ~/projects/yarisma/araclar/ag_kur.sh --kaldir
```

---

## 9 · SAHTE SUNUCU KURULUMUNDAN FARKLAR

| | prova (sahte) | **YARIŞMA** |
|---|---|---|
| Terminal 2 (sahte sunucu) | vardı | **YOK** |
| harita sekmesi `:10099/harita` | vardı | **YOK** |
| `DOW_SUNUCU` | `http://127.0.0.1:10099` | **verme** — `baslat.sh` `10.0.0.10:10001` kullanır |
| `DOW_SUNUCU_HZ` | 3.0 denenmişti | **verme** — 1.8 Hz |
| `DOW_SUNUCU_HZ_TAVAN` | 3.5 denenmişti | **verme** — 2.0 (⛔ aşarsan sunucu 400 döner) |
| `DOW_KMT_VETO=0` | tezgâhta veriliyordu | **verme** |
| ethernet | gerekmiyordu | **ŞART** — adım 1 |
| GCS komutu | env'li uzun satır | **sadece `~/projects/yarisma/baslat.sh`** |

⭐ **Kural: `baslat.sh`'a hiçbir `DOW_SUNUCU*` değişkeni verme.** Yarışma
değerleri betiğin içinde. Tek istisna kamera cihazı (`DOW_KAM_KAYNAK`).

---

## 10 · SORUN GİDERME

`kaynak = MANUEL` ise görev başlamamıştır; `sebep` alanına bak:

| sebep | ne yap |
|---|---|
| `gorev_baslamadi` | gaz dibe → `ARM` → `GÖREVİ BAŞLAT` |
| `gudum_bayat` | `KÖKEN KUR`'a bas (`güdüm` alanında `⛔ KOKEN_YOK` çıkar) |
| `pilot_vetosu` | `MANUEL` → tekrar `OTONOM` |
| `teslim_suresi` | panel sekmesini öne al |
| `paket_kesildi` | panel sekmesini yenile |

ARM tutmuyorsa → `gaz kanalı` satırı; `⛔ ARM İÇİN DİBE ÇEK` diyorsa gazı indir.

İrtifa saçmaysa → `KÖKEN KUR`'a tekrar bas.

Tam teşhis:
```bash
python3 -c "
import json,urllib.request
d=json.load(urllib.request.urlopen('http://127.0.0.1:8810/api/durum',timeout=5))
k=d['komut']; a=d['arac']
print('kip',k.get('kip'),'kaynak',k.get('kaynak'),'SEBEP',k.get('sebep'))
print('arm',k.get('arm'),'gorev',k.get('gorev'),'koken',a.get('koken'))
print('hedef',(d.get('hedef') or {}).get('var'),(d.get('hedef') or {}).get('yas'))
print('kalan',(d.get('kontrol') or {}).get('kalan'))"
```

---

## HIZLI ÖZET

```bash
sudo ~/projects/yarisma/araclar/ag_kur.sh                      # 1  ağ
python3 ~/projects/yarisma/araclar/sunucu_testi.py --sure 20   # 2  sunucu
~/projects/yarisma/skydagger/baslat_backend.sh                 # 3  backend
~/projects/yarisma/baslat.sh                                   # 4  GCS (yeni terminal)
```

3. adımın konsolunda: `/connect` → `RC_ENABLE` → 2S pili tak (MAVİ) → `STOP` → `EXTERNAL`

→ `http://127.0.0.1:8810` → **KÖKEN KUR · OTONOM · gaz dibe · ARM · GÖREVİ BAŞLAT**
