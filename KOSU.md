# KOŞU KILAVUZU — baştan sona çalıştırma

Bu dosya **tam yarışma provasının** komutlarını sırasıyla verir.
Yarışmadan tek farkı: hedef İHA'nın konum verisi sunucudan değil
**bizim haritamızdan** gelir. Diğer her şey (kamera, dedektör, görsel
devir, kilit sayacı, telemetri, hakem) yarışmadaki gibidir.

> Her komuttan önce **`cd ~/projects/yarisma`**. Betikler depo içinde.

---

## 0 · TEMİZLİK — her başlangıçta

Eski süreçler portları tutuyorsa yeni olanlar sessizce başlamaz ve
**GCS eski sürece bağlanır** (bu tuzağa düşüldü: köken bambaşka bir
koordinat verdi).

```bash
cd ~/projects/yarisma
for p in $(pgrep -f drone_yki; pgrep -f sahte_sky; pgrep -f sahte_sun); do kill -9 $p; done
ss -ltn | grep -E ":8766|:8810|:10099" || echo "portlar bos"
```

`portlar bos` yazmalı. Yazmıyorsa devam etme, portu tutanı bul:

```bash
ss -ltnp | grep -E ":8766|:8810|:10099"
```

> ⛔ `pkill -f drone_yki` **KULLANMA** — kendi kabuğunu öldürüyor
> (CLAUDE.md §9). Yukarıdaki PID'li hâli kullan.

---

## 1 · KAMERAYI BUL (bir kez, kartı taktıktan sonra)

```bash
cd ~/projects/yarisma
python3 gercek/kamera_ayari.py --tara
```

Yakalama kartının cihazını not et (genelde `/dev/video2`). Kart yoksa
`/dev/video0` dizüstü webcam'idir — zincir yine tam çalışır, sadece
görüntü FPV yerine oda olur.

---

## 2 · TERMİNAL 1 — Skydagger backend

Komitenin backend'i. ESP32 ile konuşan tek şey budur; bizim yazılım
ona TCP/UDP ile bağlanır.

```bash
cd ~/projects/yarisma
./skydagger/baslat_backend.sh
```

Açılan konsolda **sırayla** (rehber §5):

```
/connect          ESP32'nin portunu bulur (/dev/ttyUSB0)
RC_ENABLE         RC yolunu açar
                  → ŞİMDİ 2S pili modüle tak → ışık MAVİ olmalı
STOP              sarı olur; durdurmanın çalıştığını doğrular
EXTERNAL          bizim yazılım devralır
```

| port | ne |
|---|---|
| `8765` | backend web arayüzü |
| `8766` | komut + telemetri (TCP) — GCS buraya bağlanır |
| `8767` | RC paketleri (UDP) — GCS buraya basar |

**İlk kurulumda bir kez:** `./skydagger/kur.sh <skydagger-backend.exe yolu>`

---

## 3 · TERMİNAL 2 — sahte yarışma sunucusu + harita

Yarışma sunucusunun yerine geçer. Hedefin konumunu **sen** vereceksin.

```bash
cd ~/projects/yarisma
python3 araclar/sahte_sunucu.py --port 10099 --desen elle --irtifa 40
```

| seçenek | ne yapar |
|---|---|
| `--desen elle` | hedefi haritadan sürüklersin (x/y) |
| `--irtifa 40` | hedefin başlangıç irtifası; sayfadaki kaydırıcı değiştirir (z) |
| `--merkez oto` | *(varsayılan)* hedefi **bizim kendi konumumuza** göre yerleştirir |

Yarışma şemasının **birebir aynısını** yayınlar (`konumBilgileri`,
`iha_enlem`, `iha_hizi`, `zaman_farki`) ve 2 Hz sınırını gerçekten
denetler.

---

## 4 · TERMİNAL 3 — yer kontrol istasyonu (GCS)

```bash
cd ~/projects/yarisma
DOW_SUNUCU=http://127.0.0.1:10099 DOW_KAM_KAYNAK=/dev/video2 \
DOW_KAM_W=640 DOW_KAM_H=480 ./baslat.sh
```

| değişken | ne |
|---|---|
| `DOW_SUNUCU` | sahte sunucumuz (yarışmada `http://10.0.0.10:10001`) |
| `DOW_KAM_KAYNAK` | 1. adımda bulduğun kamera |
| `DOW_KAM_W/H` | **640x480 ŞART** — optik kalibrasyon bu çözünürlükte |

`baslat.sh` diğer bütün ayarları (GNSS, optik, çevirici, kumanda
eksenleri, kalkış irtifası) kendisi verir. Açılışta şunları görmelisin:

```
DEDEKTÖR  : yüklendi
KAMERA    : /dev/videoX  640x480
SUNUCU    : ... — giriş başarılı
```

⛔ **"ÇÖZÜNÜRLÜK UYUŞMAZLIĞI" uyarısı çıkarsa DUR.** Menzil hesabı
yanlış olur; `DOW_KAM_W/H`'yi düzelt.

---

## 5 · TARAYICI — iki sekme yan yana

| adres | ne |
|---|---|
| `http://127.0.0.1:8810` | **panel** — FPV, tespit kutusu, telemetri, düğmeler |
| `http://127.0.0.1:10099/harita` | **harita** — hedefi sürükle + irtifa kaydırıcısı |

---

## 6 · PANELDE SIRA

1. **`KÖKEN KUR`** — araç yerdeyken. Mesajda koordinatın doğru
   çıktığını gör. Bütün metre hesabı buna göre.
2. **`OTONOM`** — yalnız **kipi** seçer, görevi BAŞLATMAZ.
3. ⛔ **Sol pad'deki GAZ çubuğunu EN DİBE çek.** Uçuş kartı gaz
   ≤ ~1050 µs olmadan **ARM ETMEZ** (`min_check`). Panelin sanal gaz
   çubuğu açılışta ORTADA (0.00 = 1500 µs) durur ve merkeze DÖNMEZ —
   çektiğin yerde kalır. Panelde `gaz kanalı` satırı
   `✔ arm edilebilir` yazmalı.
4. **`ARM`** — mandal: bir kez bas arm olur, tekrar bas disarm olur.
   Onay ister (motorlar dönecek). ⛔ **Pervaneler çıkarılı olsun.**
5. **`GÖREVİ BAŞLAT`** — bu düğme YALNIZ otonom kipte görünür ve yalnız
   araç ARM'ken çalışır. Araç `KALKIS_VZ` ile `KALKIS_ALT`'a tırmanır,
   sonra `ISTASYON`a geçip hedefe yönelir. Aynı düğme `GÖREVİ DURDUR`
   olur.
6. **Haritadan hedefi sürükle**; sağdaki kaydırıcıyla irtifayı ver.

> ⛔ **SERT AYRIM:** `MANUEL`'e basmak görevi DURDURUR ve `OTONOM`'a
> dönmek onu kendiliğinden geri GETİRMEZ. Otonomdayken sanal çubuk
> alanı grilenir ve tıklanamaz.

**Ön uçuş listesi 8/8 olmalı.** Değilse eksik madde kırmızı yazar.

---

## 7 · NE GÖRECEKSİN

### Panel

| alan | beklenen |
|---|---|
| kip şeridi | `🚀 GÖREV SÜRÜYOR — KALKIS tırmanıyor … m` |
| `gaz kanalı` | ARM'dan önce `✔ arm edilebilir` |
| `kaynak` | `OTONOM`, `sebep` boş |
| `güdüm` | `KALKIS` → `ISTASYON` → (10 tespitte) `GORSEL` |
| `telemetri yaşı` | gps/duruş **< 0.1 s** |
| `burun / rota` | araç düz giderken fark ~0 |
| FPV | görüntü akıyor, tespit kutusu çiziliyor |

**Görsel devir:** dedektör **10 ardışık karede** hedefi görürse
`ISTASYON → GORSEL` atlar. 20 ardışık tespitsiz karede GPS'e döner.

**Görsel fazın İKİ alt fazı var** (şartname 6.1.4):

| alt faz | ne yapar |
|---|---|
| **KILIT** | kutuyu **ekranın %8'inde TUTAR** ve kilit süresini biriktirir. Kip şeridi `kilit 2.3 / 5.0 s` yazar; FPV üstünde de `KİLİT x.x/5.0 s` görünür |
| **TERMINAL** | ister sağlandı (10 s'lik pencerede kümülatif ≥5 s, kutu eksenin ≥%5'i) → **vuruşa gider**. Mandallı: geri dönmez |

⛔ **Kilit menzili METRE DEĞİL, EKRAN YÜZDESİDİR.** Şartname ölçütü
piksel: kutu, yatay **veya** dikey eksenin ≥%5'i. Kadraj 640x480 ise
eşikler 32 px (yatay) / 24 px (dikey). Denge noktası `DOW_KILIT_DENGE=8`
→ **51 px**, yani eşiğin %60 üstünde. Pay şart: kutu kareden kareye
titrer, tam %5'te dengelenirsek sayaç sürekli girip çıkar ve kümülatif
5 s hiç dolmaz.

⛔ **Kilit isteri sağlanmadan terminal faza GEÇİLMEZ.** `DOW_KILIT_FAZI=1`
(varsayılan). Kapatmak için `DOW_KILIT_FAZI=0` — ama kapalıyken kilit
isteri fiziksel olarak sağlanamıyor (ölçüldü: 76 uçuşta 0 kilit, en iyi
kümülatif 1.64 s).

### Harita

Büyük yazı **DÖNÜŞ YÖNÜ**: hedefi sağa koy → yaw komutu `+`, sola koy
→ `−`, açı büyüdükçe komut büyür.

⚠ Yeşil ok **yerde aracın burnunu** gösterir, hedefi değil. Yerdeki
araç dönemediği ve hız hatası hep azami olduğu için `pitch` daima
`+1.00`'de doyar — bu normaldir, sayfa "⚠ çubuk DOYUMDA" yazar.

---

## 8 · DURDURMA ve KAPANIŞ

**Uçuş sırasında:** panelde **`DISARM`** (anında, onaysız).
Acil: **`FAILSAFE — DİKEY İNİŞ`**, son çare **`PAKET KES`**.

⛔ **OTONOM'da kumanda güdüme karışmaz.** Durdurmak için panel:
`MANUEL` / `DİKEY İNİŞ` / `PAKET KES`.

**Kapanış sırası (backend konsolunda):**

```
EXTERNAL STOP        bizim yazılımın kontrolünü bırak
/disconnect          ⛔ ATLAMA — ESP kötü boot moduna düşebilir
                     → pili çek
                     → USB'yi çek
```

Sonra Terminal 3 ve 2'de `Ctrl+C`.

---

## 9 · SORUN GİDERME

Panelde **`kaynak = MANUEL`** ise görev başlamamıştır. `sebep` alanı
hangi şartın düştüğünü söyler:

| sebep | anlamı | ne yapmalı |
|---|---|---|
| `gudum_bayat` | güdüm setpoint üretmiyor | **köken kurulmamış olabilir** — `güdüm` alanında kırmızı `⛔ KOKEN_YOK` çıkar. Telemetri de ölmüş olabilir (`BAGLANTI_YOK`) |
| `pilot_vetosu` | panel izin göndermiyor | `MANUEL` → tekrar `OTONOM` |
| `teslim_suresi` | 3 s'dir insan girdisi yok | panel sekmesini öne al |
| `paket_kesildi` | ne panel ne kumanda | panel sekmesini yenile |
| `gorev_baslamadi` | OTONOM seçili ama görev başlatılmamış | gaz dibe → `ARM` → `GÖREVİ BAŞLAT` |

**İrtifa saçma görünüyorsa** (ör. `-892 m` yazarken uçuş kartı 1 m diyor):
`KÖKEN KUR`'a **tekrar bas**. Köken hem konum hem irtifa referansını
yeniler, ve artık güdümün zemin referansını da sıfırlıyor. `yükseklik`
satırındaki ham sayılar (`AMSL … köken … baro …`) hangisinin kaydığını
gösterir. Görev başlatıldığında zemin referansı zaten otomatik yenilenir.
| `-` ve kip `MANUEL` | OTONOM'a hiç geçilmemiş | `OTONOM`'a bas |

**Tek satırlık tam teşhis:**

```bash
cd ~/projects/yarisma && python3 -c "
import json,urllib.request
d=json.load(urllib.request.urlopen('http://127.0.0.1:8810/api/durum',timeout=5))
k=d['komut']; a=d['arac']; g=d.get('gudum') or {}
print('kip     :',k.get('kip'))
print('kaynak  :',k.get('kaynak'),'  SEBEP:',k.get('sebep'))
print('arm     :',k.get('arm'))
print('koken   :',a.get('koken'),' canli:',a.get('canli'),' uydu:',a.get('uydu'))
print('yas_gps :',a.get('yas_gps'),' yas_durus:',a.get('yas_durus'))
print('gudum   :',g)
print('hedef   :',(d.get('hedef') or {}).get('var'),(d.get('hedef') or {}).get('yas'))
print('oto     :',d.get('oto_cubuk'))
print('kalan   :',(d.get('kontrol') or {}).get('kalan'))
"
```

---

## 10 · VARYASYONLAR

### Görsel güdüm kapalı (yalnız GPS)

```bash
DOW_SUNUCU=http://127.0.0.1:10099 DOW_KAM_KAYNAK=/dev/videoYOK \
  ./baslat.sh --gorsel-yok
```
Dedektör hiç yüklenmez. Kamerasız sahnede dedektör hayalet üretip
güdümü `GORSEL` fazına kaçırabiliyor; sadece GPS'i sınarken bunu
istemeyiz.

### Hedef tazeliğini 3 Hz yap (⛔ YALNIZ YER TESTİ)

```bash
# Terminal 2
python3 araclar/sahte_sunucu.py --port 10099 --desen elle --irtifa 40 --hz-siniri 3.5
# Terminal 3
DOW_SUNUCU=http://127.0.0.1:10099 DOW_SUNUCU_HZ=3.0 DOW_SUNUCU_HZ_TAVAN=3.5 \
DOW_KAM_KAYNAK=/dev/video2 DOW_KAM_W=640 DOW_KAM_H=480 ./baslat.sh
```

⛔ **YARIŞMADA GEÇERSİZ.** Gerçek sunucu 2 Hz üzerini HTTP 400 + hata
kodu 3 ile reddeder. Bu ayarla koşarken ekranda `⚠⚠ ... YARIŞMA SINIRI
2 Hz` uyarısı görürsün — o uyarı varsa yarışma ayarında **değilsin**.

### Gerçek yarışma sunucusu

```bash
cd ~/projects/yarisma
./baslat.sh
```
`baslat.sh` gerçek sunucuyu (`http://10.0.0.10:10001`), takım numarasını
ve 1.8 Hz'i kendisi verir. Ethernet kablosu takılı ve IP
`10.0.0.114/24` olmalı.

---

## 11 · PERVANESİZ YER SINAMALARI

```bash
# yön işareti (Y_ISARET) — aracı elinde 4 burun yönüne çevir
python3 gercek/yon_testi.py --mod cevir

# hedefe yönelme — araç sabit, hedef gezer
python3 gercek/yon_testi.py --mod hedef --sure 120

# güdümün istediği yön, canlı
python3 gercek/cubuk_izle.py

# hedef akışı (Hz, yaş, reddedilen)
python3 gercek/hedef_testi.py

# dedektör güveni, canlı
python3 gercek/tespit_izle.py

# birim bekçileri
python3 -m pytest tests/ -q
```

Hepsi **pervanesiz ve DISARM** koşulur. `yon_testi` için panelde
`KÖKEN KUR` + `OTONOM` basılı olmalı ve hedef akışı taze olmalı.
