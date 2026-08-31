# TEKNOFEST 2026 · SAVAŞAN İHA AVCI DRONE — YER KONTROL İSTASYONU

Takım **hamidiye**. Tek araç, tek arayüz: **avcı drone**. Hedef İHA yarışma
komitesinin kontrolündedir; konumu yarışma sunucusundan **kasten bozulmuş**
olarak gelir ve `gercek/gnss_filtre.py` tarafından temizlenir.

---

## 1 · YARIŞMA GÜNÜ — SIFIRDAN ÇALIŞTIRMA

### 1.0 · Donanımı tak (sıra önemli)

| # | ne | not |
|---|---|---|
| 1 | **Skydagger ESP32** (ELRS) → USB | ⛔ 2S pilini **HENÜZ TAKMA** |
| 2 | **FPV yakalama kartı** → USB | verici açık olsun |
| 3 | **Kumanda** → USB, aç | EdgeTX: **USB Mode = Joystick** |
| 4 | **Ethernet kablosu** → yarışma ağı | doküman §2 |
| 5 | **Drone pili** | yerde, pervaneler takılı ama alan boş |

Doğrula:
```bash
ls -l /dev/serial/by-id/ ; ls /dev/video* ; ls /dev/input/js*
```
- `usb-Silicon_Labs_CP2102_...` → **ESP32**
- `/dev/video2` → yakalama kartı  ·  `/dev/input/js0` → kumanda

⛔ `ttyUSB0/1` numaraları takma sırasına göre değişir; **daima `by-id` kullan.**

### 1.1 · Sunucu bilgilerini gir

`baslat.sh` içindeki iki satır:
```bash
export DOW_SUNUCU="http://<HAKEMİN_VERDİĞİ_ADRES>:<PORT>"
export DOW_TAKIM_NO="<HAKEMİN_VERDİĞİ_NUMARA>"      # ⛔ 0 BIRAKMA
```
Kullanıcı adı/şifre zaten yazılı (`hamidiye`).

Bağlantıyı önden sına:
```bash
python3 araclar/sunucu_testi.py
```

### 1.2 · Skydagger backend — **Terminal 1**, açık kalır
```bash
cd ~/projects/yarisma/skydagger
./baslat_backend.sh
```
Konsola **sırayla**:
```
/connect /dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0
RC_ENABLE          → ŞİMDİ modüle 2S pili tak → ışık MAVİ
STOP               → sarı
EXTERNAL
```
⛔ `/connect`'i yalnız yazma — portu **elle** ver.

### 1.3 · Yer kontrolü — **Terminal 2**, açık kalır
```bash
cd ~/projects/yarisma
./baslat.sh
```
Açılışta doğrula:
```
SUNUCU  : http://...   takım <no>   kadı hamidiye
GÖNDERİM: 1.8 Hz  (⛔ doküman sınırı 2 Hz)
GNSS    : süzgeç AÇIK  R=200 cm  dt=0.55 s
KAMERA  : /dev/video2  640x480     ← çözünürlük uyarısı ÇIKMAMALI
DEDEKTÖR: yüklendi
```

**Tarayıcı → `http://localhost:8810`**

### 1.4 · Panelde sırayla
1. İlk 5 s `SAFE PENCERESİ` — **modülün MAVİ ışığını o an doğrula**
2. **KÖKEN KUR** — drone yerde ve hareketsizken, uydu ≥ 10 iken
3. Ön uçuş listesi **8/8 yeşil**
4. `SUNUCU` rozetinde gönderim sayacı **artıyor** olmalı

---

## 2 · GÖREVİN İCRASI

| an | ne yaparsın | neye bakarsın |
|---|---|---|
| Hedef havalandı | — | HEDEF `GPS akışı: VAR, yaş < 1 s` |
| Kalkış | **ARM (BASILI TUT)** + **MANUEL**, elle 30-50 m'ye çık | araç dengede |
| Takip | **OTONOM** | `kaynak: OTONOM` · `güdüm: ISTASYON` |
| Yaklaşma | izle | HEDEF `kuzey/doğu ⟶ uzaklık` **AZALIYOR** |
| Görsel temas | izle | `güdüm: GÖRSEL` · FPV'de kutu |
| Kilit | otomatik | `kilit` sayacı · sunucuya paket gider |

⛔ **Otonoma yerden geçme.** Kalkış fazı kapalıdır (`DOW_KALKIS_ALT=0`);
OTONOM'a basınca araç **hemen hedefe yönelir**.

### Çıkış — üç yol, ezberle
1. **Kumanda çubuğuna dokun** → anında MANUEL, **mandallı** (kendiliğinden dönmez)
2. Panelde **MANUEL**
3. **⛔ FAILSAFE — DİKEY İNİŞ** → görevi keser, olduğu yerde sabit hızla iner

---

## 3 · KAPATMA (sıra önemli)

Backend konsolunda:
```
EXTERNAL STOP
/disconnect
```
⛔ `/disconnect` atlanırsa ESP32 kötü boot moduna düşebilir.

Sonra pili, sonra USB'yi çek. Ardından:
```bash
cd ~/projects/yarisma
./baslat.sh --kapat && ./skydagger/baslat_backend.sh --kapat
ss -lntu | grep -E ":8765|:8766|:8767|:8810"     # boş çıkmalı
```
⚠ **Fişi çekmek yazılımı kapatmaz** — süreçler ayakta kalır.

---

## 4 · HABERLEŞME (Doküman 2026 · birebir)

| uç | ne |
|---|---|
| `POST /api/giris` | `{"kadi","sifre"}` |
| `GET /api/sunucusaati` | sunucu saati |
| `POST /api/telemetri_gonder` | telemetrimiz → **yanıtta hedef İHA verileri** |

**Gönderdiğimiz paket (§7.1)** — 14 alan, `drone_yki._telemetri()`:
`takim_no · enlem · boylam · irtifa · dikilme · yonelme · yatis · hiz ·
mod · kilitlenme · hedef_x_merkezi · hedef_y_merkezi · hedef_genislik ·
hedef_yukseklik`

**Aldığımız yanıt (§7.2):** `sunucu_saati` + `hedef_iha_verileri[]`
(`takim_no · enlem · boylam · irtifa_ev · hiz · saat_farki`)

⛔⛔ **HIZ SINIRI (§7):** en az 1 Hz, **2 Hz üzeri 400 + hata kodu 3**.
Kod 1.8 Hz'de sınırlı ve ikinci bir güvence olarak 0.5 s'den sık göndermeyi
reddediyor.

⚠ **Hedef tazeleme hızı = gönderim hızımız.** Hedef verisi ayrı bir akışta
değil, telemetri **yanıtında** geliyor. 1.8 Hz'de paketler arası 0.55 s;
20 m/s giden bir hedef bu sürede **11 metre** yol alır. Süzgecin ölü hesabı
(dead reckoning) ve 1 s'lik ileri taşıması (lead) bunu kapatmak içindir.

### ⛔ AÇIK SORU — sahada teyit et
Doküman §8 kilitlenme bilgisi göndermeyi **zorunlu** kılıyor ama §4'teki
API listesinde o uç **YOK**. Kod `/api/kilitlenme_bilgisi` varsayıyor.
**Hakemden doğru URL'yi teyit et**; yanlışsa kilit paketleri 404 alır ve
puan kaybedilir.

---

## 5 · GNSS SÜZGECİ — bozuk hedef GPS'i

Hedef konumu kasten bozulmuş gelir: konum gürültüsü, ani sıçrama, veri
kesintisi, gecikme. `gercek/gnss_filtre.py` bunu temizler.

- **CT-EKF** (coordinated-turn genişletilmiş Kalman): hedefin sabit dönüş
  hızıyla döndüğünü varsayar → **manevrayı öngörür**
- **Mahalanobis kapısı**: jammer sıçramasını istatistiksel olarak reddeder
- **Kaçış**: kapı üst üste reddederse belirsizlik şişirilir → yeni rejime
  2-3 s'de yeniden kilitlenir
- **Ölü hesap**: kesintide son hız+dönüşle ileri gider (`DOW_GNSS_DR_MAKS`)
- **Lead**: çıktı `DOW_GNSS_TELAFI` kadar ileri taşınır (GPS gecikmesi)

⛔ Süzgeç **yerel metrik çerçevede** çalışır (enlem/boylamda değil) ve
**SANTİMETRE** ister; çevrimi `HedefSuzgeci` yapar.

### En önemli ayar: `DOW_GNSS_R`
Ölçüm gürültüsü (cm). **Gerçek bozulma büyüklüğüne eşlenmeli.** Ölçüldü:

| bozulma | R | reddedilen | iyileşme |
|---|---|---|---|
| 2 m | **200** | 1/200 | **%64** |
| 2 m | 50 (ayarsız) | **150/200** | çöküyor |
| 2 m | 200, lead kapalı | 1/200 | %11 |

**Sahada ayarı:** panelde `gnss.reddedilen` sayacı hızla artıyorsa **R küçüktür**, yükselt.

---

## 6 · YERDE KANITLANMIŞ OLANLAR

| ne | nasıl |
|---|---|
| **`Y_ISARET=+1.0` doğru** | `yon_testi.py --mod cevir` · 37 örnek, 5 burun yönü · toplanma H0 **0.992** vs H1 0.156 · hedefe sapma **+0.4°** vs −92.9° |
| Çubuklar hedefi takip ediyor | `cubuk_izle.py` · 55-59 m'de **69 uyumlu / 0 uyumsuz** |
| Manuel kontrol (kumanda + panel) | eşleme doğru |
| ARM — iki kaynaktan da | panel (basılı tut) + kumanda anahtarı |
| Pilot devralma mandalı | çubuğa dokununca `sebep=pilot_devraldi`, geri gelmez |
| Failsafe dikey iniş | tezgâhta: kanallar 1899 µs, TUT→IN, sabit hız |

## 7 · AÇIK RİSKLER

| risk | durum |
|---|---|
| Dikey iniş **hiç uçmadı** | ilk kullanımı güvenli irtifada, pilot hazır |
| Alçalma hızı ölçülmedi | `DOW_INIS_CUBUK=-0.35` başlangıç; ölç, ayarla |
| `MENZIL_C` türetme | yalnız **görsel** fazı etkiler, GPS fazını değil |
| Hedef telemetri sürekliliği | yerde %43 kesinti ölçüldü (gövde engeli); havada izle |
| Kilitlenme uç adresi | §4'te yok — **hakemden teyit et** |

---

## 8 · ARAÇLAR

```bash
python3 araclar/sunucu_testi.py          # sunucu bağlantısı + paket biçimi
python3 gercek/hedef_testi.py            # hedef akışı (Hz, yaş, red)
python3 gercek/kamera_ayari.py --tara    # yakalama kartı
python3 gercek/cubuk_izle.py             # güdümün istediği yön, canlı
python3 gercek/yon_testi.py --mod cevir  # yön işareti (yerde, pervanesiz)
python3 -m pytest tests/ -q              # 100 bekçi
```

## 9 · KURULUM (yeni makinede)
```bash
git clone <depo> ~/projects/yarisma && cd ~/projects/yarisma
pip install -r requirements.txt
./skydagger/kur.sh          # Skydagger backend
```
