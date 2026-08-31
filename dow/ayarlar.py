# -*- coding: utf-8 -*-
"""
================================================================================
MERKEZİ AYARLAR — panelden CANLI değiştirilebilir
================================================================================
Gazebo'daki `bbox_ibvs.Cfg` ile aynı desen: SINIF NİTELİKLERİ. Güdüm döngüsü
her karede `Ayar.<ALAN>` okur; panel sınıf niteliğini değiştirince bir sonraki
kareden itibaren geçerli olur — UÇUŞ SIRASINDA, yeniden başlatmadan.
(CLAUDE.md §6'nın DoW karşılığı.)
================================================================================
"""
import os


def _f(ad, v):  return float(os.environ.get(ad, v))
def _b(ad, v):  return os.environ.get(ad, str(int(v))).strip() not in ("0", "", "false", "False")


class _IbvsKopru:
    """Panelin IBVS ayarlarını canlı değiştirebilmesi için köprü:
    Ayar.<ALAN> okunduğunda/yazıldığında IbvsCfg'ye yansır."""
    pass


class Ayar:
    # ================= AŞAMA ANAHTARLARI =================
    # ⚠ GELİŞTİRME KİPİ (2026-08-22, kullanıcı kararı):
    #   Şimdilik BOZUK GPS + filtre yerine DOĞRUDAN TRUTH kullanılıyor.
    #   Amaç: GPS güdümünün kendisini (istasyon tutma) filtre gürültüsünden
    #   ARINDIRILMIŞ olarak düzeltmek. Bu iş bitince GPS_KAYNAK="filtre"
    #   yapılıp gnss_filtre.py yeniden devreye alınacak.
    #   ⛔ YARIŞMADA "truth" KULLANILAMAZ — orada bu kanal gelmez.
    GPS_KAYNAK   = os.environ.get("DOW_GPS_KAYNAK", "truth")   # "truth" | "filtre"

    # ⚠ Görsel faz ŞİMDİLİK KAPALI (kullanıcı kararı): önce GPS istasyon
    #   tutma düzelsin, sonra görsele geçilsin. Kapalıyken dedektör hiç
    #   koşmaz -> döngü 10 FPS yerine ~50 Hz olur, testler ÇOK hızlanır.
    # ================= GÜDÜM KİPİ (panelden CANLI seçilir) =================
    # Kullanıcı isteği (2026-08-22): "arayüze üç buton koy — hibrit, gps,
    # görsel. gps'e basınca sadece GPS güdümü, görsele basınca sadece görsel,
    # hibritte faz geçişiyle. Böylece sadece GPS'te uçurup detection modeli
    # aracı tam olarak nasıl tespit ediyor görebiliriz."
    #   "gps"    : YALNIZ istasyon tutma. Görsel faza ASLA geçilmez.
    #              Dedektör yine koşar (panel için) ama güdüme GİRMEZ.
    #   "gorsel" : kilit kurulunca görsele geçer ve GERİ DÖNMEZ.
    #              (İlk kilide kadar istasyon tutma yaklaştırır.)
    #   "hibrit" : 10 kare tespit -> görsel, 20 kare tespitsiz -> GPS.
    GUDUM_KIPI = os.environ.get("DOW_KIP", "hibrit").strip().lower()


    GORSEL_AKTIF = _b("DOW_GORSEL", False)

    # DEDEKTÖRÜ SADECE GÖSTER — güdüme GİRMEZ.
    # Kullanıcı panelde hedefin nasıl algılandığını görmek istiyor ama
    # güdüm GPS'te kalmalı. Bu anahtar dedektörü yalnız PANEL için koşturur;
    # çıktısı Beyin'e ASLA verilmez (GORSEL_AKTIF ayrı anahtardır).
    DEDEKTOR_GOSTER = _b("DOW_DET_GOSTER", True)
    DEDEKTOR_HZ     = _f("DOW_DET_HZ", 2.0)   # panel için çıkarım hızı

    # ================= PANEL MALİYET TAVANLARI =================
    # ⛔ ÖLÇÜLDÜ 2026-08-22 — arayüz UÇUŞU BOZUYORDU, yalnız yavaşlatmıyordu.
    #   izleyici.py ekranı SANİYEDE 180-330 KEZ kopyalıyordu (1920x1080 =
    #   8.3 MB/kare -> ~2 GB/s X11 trafiği) ve aynı GPU'da YOLO'yu imgsz
    #   1920'de tam hızda koşuyordu. Oyun (UE5/Vulkan) aynı GPU + aynı X
    #   sunucusunda olduğu için başarımı düştü. SONUÇ (GA04 vs GV11):
    #     istasyon hatası 5.3 m -> 25.3 m,  ≤15 m oranı %88 -> %2,
    #     v_istek 120 s boyunca 33 m/s TAVANINDA doyumda kaldı.
    #   Oyunun kendisi ~60-120 FPS basıyor; 30 Hz üstü kopyalama zaten AYNI
    #   kareyi tekrar okumak demek — bedava değil, bedelli hiçlik.
    #   ÖLÇÜLDÜ (oyun koşarken, 2026-08-22): tam kare X11 aktarımı
    #   13.3 ms + BGRA->RGB 1.25 ms = 14.6 ms. Yani 15 Hz ~ %22 çekirdek VE
    #   saniyede 15 GPU senkronu. Asıl bedel CPU değil: her XGetImage oyunun
    #   çizim boru hattını SENKRONA zorluyor. Eski sınırsız döngü bu yüzden
    #   oyunu aç bırakıyordu. Dedektör zaten 5 Hz'de kutu üretiyor.
    PANEL_YAKALA_HZ = _f("DOW_PANEL_YAKALA_HZ", 15.0)
    PANEL_DET_HZ    = _f("DOW_PANEL_DET_HZ", 5.0)
    # ⛔ GÖRSEL FAZDA DA TAVAN ŞART (ölçüldü 2026-08-22).
    #   Görsel fazda YOLO her kontrol tikinde koşunca (~19 Hz) oyun aç kaldı
    #   ve GPS istasyon tutma 4.96 m -> 17.76 m'ye BOZULDU; `v_istek`
    #   karelerin %59'unda 33 m/s tavanında doyuma girdi (GPS kipinde %12).
    #   Yani dedektörün hızı GÜDÜMÜ bozuyor. Güdüm zaten son kutuyu
    #   tutuyor; çıkarımı tavanlamak kontrol bant genişliğini de ARTIRIR.
    GORSEL_DET_HZ   = _f("DOW_GORSEL_DET_HZ", 10.0)
    # ⭐ KOL C — çıkarımı ZAMANLAYICI yerine YENİ KARE olayına bağla.
    #   Yakalama 15 Hz iken 10 Hz zamanlayıcı, karelerin bir kısmını İKİNCİ
    #   KEZ tarar (aynı piksel, aynı sonuç, tam bedel). Kapı açıkken çıkarım
    #   yalnız yeni kare geldiğinde koşar; GORSEL_DET_HZ üst sınır kalır.
    DET_YENI_KARE   = _b("DOW_DET_YENI_KARE", False)
    # ⭐ GÖRÜŞ İŞ PARÇACIĞI (2026-08-24) — yer-kontrol `model-fps` mimarisi.
    #
    #   SORUN (ÖLÇÜLDÜ, kampanya HZ4): bizde YOLO kontrol döngüsünün İÇİNDE
    #   koşuyor. Çıkarım 9.3 -> 16.2 Hz'e çıkarılınca kontrol döngüsü
    #   40.3 -> 22.3 Hz'e DÜŞTÜ; araç istasyonu tutamadı (hata 8.3 -> 16.5 m),
    #   görsel devir HİÇ olmadı, isabet 1 -> 0.
    #   Yani yukarıdaki tavanlar bir çözüm değil, bu blokajın SEMPTOMU.
    #
    #   ONLARDA: `kontrol_dongusu` 50 Hz kendi iş parçacığında (time.sleep(0.02)),
    #   `dedektor_dongusu` AYRI iş parçacığında tavansız ("kare varsa inference
    #   kendi hizinda pace'lenir; ekstra sleep YOK"). Güdüm, dedektörün son
    #   çıktısını kilitli ANLIK GÖRÜNTÜDEN okur -> YOLO ne kadar sürerse sürsün
    #   güdüm 50 Hz döner.
    #
    #   AÇIKKEN: çıkarım görüş iş parçacığında koşar, kontrol döngüsü yalnız
    #   son kutuyu OKUR (bloke YOK). GORSEL_DET_HZ üst sınır olarak kalır.
    #   ⚠ VARSAYILAN KAPALI — açılması ölçümle kararlaşır (§6).
    GORUS_ISP       = _b("DOW_GORUS_ISP", False)
    PANEL_OLCEK     = _f("DOW_PANEL_OLCEK", 0.5)   # JPEG'e giden küçültme
    # ⭐ BAYAT KUTUYU EKRANA BASMA (2026-08-27, kullanıcı isteği).
    #   Çıkarım art arda ıskalayınca son kutu ekranda saniyelerce kalıyor ve
    #   operatöre hedef hâlâ oradaymış gibi görünüyordu. Bu eşikten yaşlı
    #   kutu PANELE ÇİZİLMEZ. ⛔ YALNIZ GÖSTERİM: güdüm ve kayıt karesi
    #   etkilenmez (bkz. kosu.py'deki not). Geri dönüş: DOW_PANEL_KUTU_TAZE=0
    PANEL_KUTU_TAZE  = _b("DOW_PANEL_KUTU_TAZE", True)
    PANEL_KUTU_YAS_S = _f("DOW_PANEL_KUTU_YAS_S", 0.3)

    # ================= KALKIŞ =================
    KALKIS_ALT_M   = _f("DOW_KALKIS_ALT", 45.0)   # zemine göreli
    KALKIS_VZ      = _f("DOW_KALKIS_VZ", 12.0)
    KALKIS_TOL_M   = 3.0

    # ================= İSTASYON (GPS fazının HEDEFİ) =================
    # Gazebo'daki çözülmüş tasarım: hedefin KUYRUĞUNDA, biraz ALTINDA dur.
    # Kamera 26.5° YUKARI baktığı için "altında" olmak hedefi kadraja sokar.
    # ⭐ ÖLÇÜLDÜ (GA03 taraması + GA04 n=4 doğrulaması): 15 m EN İYİ NOKTA.
    #   35 m -> ist_hata 6.28 m, tespit %48, kutu 20 px
    #   25 m -> ist_hata 5.63 m, tespit %77, kutu 29 px
    #   15 m -> ist_hata 5.28 m, tespit %90, kutu 46 px   <- SEÇİLDİ
    #    8 m -> ist_hata 4.81 m, tespit %79 (hedef kadraja SIĞMIYOR)
    #
    # ⭐⭐ YENİDEN ÖLÇÜLDÜ 2026-08-22 (kampanya GK+GK2, 24 uçuş) — 8 m / 0.75.
    #   Kullanıcı isteği: "istasyonu hedef araca daha da yaklaştıralım, bir de
    #   biraz gerisine ve ALTINA alalım ki hedef kadraja girdiğinde arka planı
    #   gökyüzü olsun; detection modeli daha iyi algılayabilir."
    #   GK2 (3 kol x 4 koşu x 90 s, dönüşümlü) GERÇEK tespit oranı medyanı:
    #     15 m / 0.45  -> %66.9   kutu 47.7 px   yanlış-pozitif %11.4
    #      8 m / 0.45  -> %76.0   kutu 73.5 px   yanlış-pozitif  %4.0
    #      8 m / 0.75  -> %88.8   kutu 69.3 px   yanlış-pozitif  %3.7   <- SEÇİLDİ
    #   Kolların aralıkları HİÇ ÖRTÜŞMÜYOR (en kötü 8/0.75 = %82.9 >
    #   en iyi 8/0.45 = %79.4 > en iyi taban = %70.7).
    #   Geçerlilik eşleri geçti: hedef kadrajda %100, ist_hata/R = 0.63,
    #   kaza 0/12, en yakın 12.6 m, oturma 5.9 s (tabanla aynı).
    ISTASYON_MENZIL_M = _f("DOW_IST_MENZIL", 8.0)   # hedefin kaç m ARKASINDA
    ISTASYON_ALT_M    = _f("DOW_IST_ALT", 15.0)     # kaç m ALTINDA (oran 0 ise)
    # Alt ofseti menzile ORANTILI tut: h = R * ORAN. tan(26.5°)=0.499 ->
    # 0.45 seçildi (hedef kadraj merkezinin hafif ÜSTÜNDE dursun; gökyüzü
    # arka planı ve "alttan yaklaşma" Gazebo'da da tercih edilmişti).
    #
    # ⭐ İKİ DÜĞME BİRBİRİNDEN BAĞIMSIZ (2026-08-22 geometri hesabı):
    #   MENZİL yalnız KUTU BOYUTUNU değiştirir  (R 15->8 m: 61 -> 114 px)
    #   ORAN   yalnız GÖK PAYINI değiştirir     (0.45->0.75: 232 -> 362 px)
    #   Çünkü yükseliş açısı atan(oran) — menzilden BAĞIMSIZ.
    #   "gök payı" = hedefin kadrajda ufuk çizgisinin kaç piksel ÜSTÜNDE
    #   durduğu. Büyükse arka plan gökyüzü olur (dedektör için temiz zemin).
    ISTASYON_ALT_ORAN = _f("DOW_IST_ALT_ORAN", 0.75)
    # İleri besleme: hedefin hızı komuta DOĞRUDAN eklenir. Bu olmadan saf P
    # kontrolcü hareketli hedefi ASLA yakalayamaz (kalıcı gecikme hatası).
    ISTASYON_KP     = _f("DOW_IST_KP", 0.9)         # 1/s; konum hatası -> hız
    ISTASYON_KP_Z   = _f("DOW_IST_KPZ", 0.9)
    ISTASYON_ILERI  = _b("DOW_IST_ILERI", True)     # hedef hızı ileri besle
    # ⛔ ISTASYON_DONUS_ILERI ÇIKARILDI (2026-08-23) — ölçüldü, elendi.
    #    Ayrıntı ve sayılar: dow/gudum/gps.py başındaki not.
    V_MAX           = _f("DOW_V_MAX", 33.0)         # m/s (araç 34.6 yapabiliyor)
    VZ_MAX_TIRMAN   = 33.5
    VZ_MAX_ALCAL    = 6.95
    YAW_RATE_MAX    = _f("DOW_YAW_MAX", 120.0)      # °/s

    # ================= GÖRSEL DEVİR =================
    # ⛔⛔ YARIŞMA KURALI (kullanıcı 2026-08-22, DİSKALİFİYE SEBEBİ):
    #   "Görsel güdüm sırasında GPS verisini ASLA kullanma; mesafe verisini
    #    bile GPS'ten çekme. Görsel güdüm algoritmasına GPS verisini dahil
    #    etmek diskalifiye sebebi."
    #   Bu yüzden devir kapısı ARTIK GPS MENZİLİNE BAKMIYOR. Kapı tamamen
    #   KAMERA verisinden: ardışık N geçerli tespit.
    #   Yanlış-pozitife karşı koruma (eskiden GPS kapısı yapıyordu) şimdi:
    #     (a) ardışık 10 kare şartı — 10 kare üst üste aynı sahte kutu zor
    #     (b) ibvs.gecerli(): conf >= 0.40, kutu boyutu MENZIL_MIN..MAX
    #         aralığında (3-50 m). 140 m'de üretilen dev yanlış-pozitif
    #         (menzil 1.3 m) bu kapıdan GEÇEMEZ.
    DEVIR_KARE      = int(_f("DOW_DEVIR_KARE", 10))   # ardışık TESPİT -> görsel
    KAYIP_KARE      = int(_f("DOW_KAYIP_KARE", 20))   # ardışık TESPİTSİZ -> GPS

    # ================= ⭐ KİLİT FAZI (Teknofest şartnamesi 6.1.4) =========
    # Kullanıcı isteği (2026-08-28): "vuruş fazına geçebilmek için hedef
    # aracı, ekranın alttan/üstten %10, sağdan/soldan %25 kırpılmış bir kutu
    # içinde, 10 saniyelik periyodun kümülatif olarak en az 5 saniyesinde
    # tespit etmiş olmamız gerekiyor; bu kilit sayılıyor ve ancak ondan
    # sonra terminal vuruş fazına geçilebiliyor."
    #
    # ⛔ NİYE BU BİR DAVRANIŞ DEĞİŞİKLİĞİ: bugün görsel faza geçince araç
    #   DOĞRUDAN temasa sürüyor (hedef kutu boyutu 997 px = 1 m menzil).
    #   ÖLÇÜLDÜ (76 uçuş, çevrimdışı, araclar/kilit_olcu.py):
    #     kilit isterini sağlayan koşu   0/76
    #     10 s penceredeki en iyi toplam 1.64 s   (isteri 5.0 s)
    #     kilit ancak R <= ~9 m'de mümkün, orada kapanma ~10 m/s
    #     -> %5 bandından 1 saniyede geçip çarpıyoruz.
    #   Yani kilit, MEVCUT yasayla fiziksel olarak sağlanamaz. Kilit fazı
    #   açıkken araç önce bir MESAFE TUTAR (aşağıdaki KILIT_MENZIL_M),
    #   kilit birikince tavanı kaldırıp terminale geçer.
    #
    # ⛔ VARSAYILAN KAPALI (kill-switch). Kapalıyken güdüm BİT BİT bugünkü
    #   davranıştır — bekçi B63 ve araclar/denklik.py bunu sınar.
    KILIT_FAZI        = _b("DOW_KILIT_FAZI", False)
    # AV (Hedef Vuruş Alanı) kırpma oranları — şartname Şekil 2
    KILIT_KIRP_X      = _f("DOW_KILIT_KIRP_X", 0.25)   # soldan/sağdan
    KILIT_KIRP_Y      = _f("DOW_KILIT_KIRP_Y", 0.10)   # üstten/alttan
    # Hedefin ekranda kaplaması gereken en az oran (yatay VEYA dikey eksende).
    # Şartname sınırı %5; kendi tavsiyesi "%6 veya daha üstü" (hatalı paket
    # riskine karşı). Varsayılan tavsiyeye uyuyor.
    # ⭐ 6.0 -> 5.0 (kullanıcı kararı 2026-08-28): "eşiği yüzde 5'e indirelim".
    #   ÖLÇÜLDÜ (KILIT16, 16 uçuş, aynı loglardan iki eşik):
    #     %6 -> A kolu duz 1/4 kilit    %5 -> A kolu duz 4/4 kilit
    #   Yanlış kilit riski de ölçüldü (gerçek menzil >12 m iken "kilitli"
    #   sayılan kare): %6'da %1.2, %5'te %1.7 — artış küçük.
    KILIT_BOYUT_YUZDE = _f("DOW_KILIT_BOYUT", 5.0)
    KILIT_PENCERE_S   = _f("DOW_KILIT_PENCERE", 10.0)  # değerlendirme penceresi
    KILIT_GEREKLI_S   = _f("DOW_KILIT_GEREKLI", 5.0)   # pencerede gereken toplam
    # Bir çıkarımın alabileceği EN BÜYÜK kredi. Şartnamenin kendi toleransı
    # ("5 saniyelik kilitlenme için 200 ms'ye kadar tolerans") = 0.20 s.
    KILIT_DT_MAX_S    = _f("DOW_KILIT_DT_MAX", 0.20)
    # ⭐ KİLİT FAZINDA TUTULACAK MESAFE (m) — PI'nın denge noktası.
    #   TÜRETME (§0.2): güdüm hızı v = K_FWD*(hedef_boyut - boyut) + I,
    #   I tavanı 8 m/s, K_FWD 0.35. Hedef 18 m/s uçuyor; onunla aynı hızda
    #   gitmek için v=18 gerekir -> kalıcı hata = (18-8)/0.35 = 28.6 px.
    #   hedef_boyut = 997/6.0 = 166 px  ->  denge kutusu ≈ 137 px.
    #   ÖLÇÜLEN kutu-menzil sabiti (76 uçuş): w·R ≈ 869 px·m
    #   ->  denge GERÇEK menzili ≈ 869/137 ≈ 6.3 m, kutu ekranın %7.1'i.
    #   Gereken %6 (115 px) -> ~1.2 m'lik pay var.
    #   ⚠ RİSK: 6.3 m, temas yarıçapının (2.0 m) 3 katı. Hedef kaçamak
    #     yaparsa gecikmeyle (~236 ms) erken temas olabilir — ölçülecek.
    KILIT_MENZIL_M    = _f("DOW_KILIT_MENZIL", 7.0)

    # ============ ⭐ KİLİT FAZI HIZ REGÜLATÖRÜ (2026-08-28) ============
    # KULLANICI GÖZLEMİ (uçuşu kendi gözüyle izledi): "kilit isterini
    # sağlamak için beklerken bir fren yapıyor ama öyle bir fren ki aracı
    # çok geriye düşürüyor... sert frenlerde aracın eğimi bir anda
    # değişiyor, hem tespit için sıkıntı hem hedef uzaklaşıyor hem de
    # kilit bozuluyor."
    #
    # ⛔ ÖLÇÜLDÜ VE DOĞRULANDI (KILIT16 + KILIT_KAPI, A kolu, 6366 kare):
    #     komut TEK TİKTE (20 ms) 28.00 -> 0.00 m/s   = -280 m/s²
    #     karelerin %67.4'ü tavanda (28), %6.6'sı TAM DURUŞTA (0)
    #     -> kontrolcü ORANSAL DEĞİL, AÇ-KAPA ANAHTARI
    #     139 sert fren olayının ardından 3 saniyede:
    #        menzil  4.4 m -> 23.5 m   (medyan +18.8 m geri düşüş)
    #        tespit  %62   -> %18
    #   Yani kullanıcının gördüğü döngü GERÇEK ve ölçülebilir:
    #        sert fren -> duruş sıçraması -> körlük -> hedef kaçar -> kilit sıfırlanır
    #
    # ⚠ AYNI HATA BU DEPODA BİR KEZ DAHA YAŞANDI: dikey kanalda K_CY=0.06 +
    #   tavan 1.5 ile karelerin %98.3'ü doyumdaydı ve kanal "aç-kapa"ydı.
    #   Çözüm oradaki ile aynı sınıftan: KAZANCI DÜŞÜR, TAVANI AÇ, İKİSİNİ
    #   BİRLİKTE değiştir (bkz. ibvs.py K_CY notu, 2026-08-23).
    #
    # TASARIM (§0.2 — her sayının nereden geldiği):
    #  * K_FWD 0.35 -> 0.10 (m/s)/px. Kilit fazında işe yarayan hata bandı
    #    ±50 px; 0.35 ile bu 17.5 m/s'lik komut savruluşu demek. 0.10 ile
    #    5 m/s — düzeltici ama sarsmayan.
    #  * I_MAX 8 -> 22 m/s. Nazik P, kalıcı yükü TAŞIYAMAZ; hedefin 18 m/s
    #    hızını integral taşımalı (integralin işi tam budur). 8'de kalırsa
    #    denge noktası kutuya ulaşamaz ve araç hep geride kalır.
    #  * V_MIN 0 -> 12 m/s. TAM DURUŞ komutu, hedef 18 m/s giderken saniyede
    #    18 m geri düşmek demektir. 12 m/s tabanı bunu 6 m/s'ye indirir.
    #  * V_MAX 28 -> 33 m/s. ÖLÇÜLDÜ: çeviricinin iç döngüsü saf-P olduğu
    #    için gerçekleşen hız komutun 7.4 m/s ALTINDA kalıyor — ve bu açık
    #    İKİ FAZDA DA AYNI (istasyon 33->25.6, görsel 28->20.6). Yani
    #    "görsel fazda araç yavaş" diye bir şey YOK; sadece 5 m/s daha az
    #    komut veriyoruz. 33'e çıkarmak kapanma payını 2.6 -> 7.6 m/s yapar.
    #    ⛔ YALNIZ KİLİT FAZINDA: TERMİNAL faz (bugün 7/8 vuran hâl)
    #       DOKUNULMADAN kalır, IbvsCfg.V_HUCUM=28 aynen sürer.
    #  * SLEW 20 m/s². Sert fren eşiği ölçümde 40 m/s²'ydi; 20 onun yarısı.
    #    ⚠ ÇOK YUMUŞAK OLAMAZ: çevrimdışı tarama (araclar/kilit_sim.py)
    #      fren tavanı 3-4 m/s² olduğunda 12/12 ÇARPMA gösterdi — araç
    #      yavaşlayamayıp hedefe giriyor. Alt sınır ~6 m/s².
    #  * ANTI-WINDUP (koşullu integrasyon): çıkış doyumdayken ve hata
    #    doyumu derinleştiriyorken integral DONDURULUR. Karelerin %67'si
    #    doyumda olduğu için bu şart; yoksa integral şişer, boşalması
    #    saniyeler sürer ve aşım yapar.
    #
    # ⛔ HEPSİ KILIT FAZINA ÖZELDİR. TERMİNAL faz ve GPS fazı BİT BİT
    #    değişmez (bekçi B68, araclar/denklik.py).
    KILIT_K_FWD   = _f("DOW_KILIT_KFWD", 0.10)    # (m/s)/px
    KILIT_I_MAX   = _f("DOW_KILIT_IMAX", 22.0)    # m/s
    KILIT_V_MIN   = _f("DOW_KILIT_VMIN", 12.0)    # m/s — asla tam durma
    KILIT_V_MAX   = _f("DOW_KILIT_VMAX", 33.0)    # m/s
    KILIT_SLEW    = _f("DOW_KILIT_SLEW", 20.0)    # m/s²; 0 = sınırsız (eski)


    # ================= ⛔ GELİŞTİRME DEVİR KAPISI — YARIŞMADA KULLANILAMAZ ==
    # Kullanıcı kararı (2026-08-22), gerekçesiyle:
    #   Dedektör MENZİLE şiddetle bağlı (GK2, n=2097 istasyon karesi):
    #     kuyruktan <10°, medyan 14.3 m -> ham tespit %88.2 (8/0.75'te %96.6)
    #     10-20°, medyan 20.2 m         -> %72.5
    #     20-35°, medyan 40.1 m         -> %50.0
    #     35-60°, medyan 69.5 m         -> %32.6
    #   Yani "ardışık 10 kare tespit" kapısı UZAKTA güvenilir sağlanamıyor ve
    #   görsel güdüm üzerinde çalışmayı fiilen bloke ediyor. Dedektörü ekip
    #   arkadaşı düzeltiyor; biz onu beklerken görsel yasayı geliştirebilelim.
    #
    # ⛔ İSTASYON DEVİR İSKELESİ SİLİNDİ — 2026-08-25 (§5.12, kullanıcı onayı)
    #
    #   Silinenler: YARISMA_KIPI, DEVIR_ISTASYONDAN, DEVIR_IST_HATA_M,
    #   DEVIR_IST_KARE, DEVIR_MENZIL_M, DEVIR_KARE_DEV, gelistirme_devri(),
    #   Beyin._gelistirme_devir_hazir(), _ist_kare, _devir_sebep ve bunlara
    #   bakan tüm log sütunu / tanı anahtarı / panel düğmesi / bekçi.
    #
    #   NEDEN: o kapı faz geçişi için HEDEFİN GPS'İNİ okuyordu. Kullanıcı
    #   (2026-08-25): "yarışma kuralı böyle, görsel temas sağlandıktan sonra
    #   gps verisi kullanılarak araç güdülemez; bu yüzden de eskisini komple
    #   silip bu yenisine geçiyoruz."
    #
    #   YERİNE GEÇEN: KAMERA kapısı — DEVIR_KARE / KAYIP_KARE (yukarıda).
    #   Ölçüldü (KAMERA10, n=5): imha 5/5, süre medyanı 18.2 -> 10.9 s,
    #   devir 14.8 -> 7.4 s. Kampanya: docs/kampanya/KAMERA10_DEVIR_KAPISI.md
    #
    #   ⭐ KAZANIM: faz geçişi artık GPS'e HİÇ bakmıyor. Yarışma kipi diye
    #   ayrı bir yol yok — tek yol var ve o yol yarışmada geçerli.
    #   Bekçi B13 bunu sınar; B25 (mayın testi) gereksizleştiği için silindi.

    # ================= BEKÇİ (uçuş sağlık bandı) =================
    BEKCI_AKTIF        = _b("DOW_BEKCI", True)
    BEKCI_ALT_MAX_M    = _f("DOW_B_ALT", 300.0)   # zemine göreli tavan
    BEKCI_MENZIL_MAX_M = _f("DOW_B_MENZIL", 500.0)
    # ⭐ 2026-08-26 — 1500 -> 600 (kullanıcı isteği: "drone başlangıç
    #   konumundan 500 metre falan uzaklaşırsa uçuşu durdur").
    #   ÖLÇÜLDÜ (KC1, 12/12 geçerli koşu): drone spawn'dan en fazla 354 m
    #   uzaklaşıyor, medyan 255 m. 1500 m eşiği kaçak bir koşuyu ancak
    #   54 saniye sonra yakalıyordu (28 m/s) — o süre boşa gidiyordu.
    #   600 m, en kötü GEÇERLİ koşunun 1.7 katı: meşru koşuyu kesmez.
    BEKCI_SPAWN_MAX_M  = _f("DOW_B_SPAWN", 600.0)
    # ⛔ SABİT EŞİK TEK BAŞINA YETMEZ — kodda yazılı tuzak:
    #   "Görev yeniden kurulunca başlangıç ayrımı 800-970 m çıkabiliyor ve
    #    kural MEŞRU YAKLAŞMAYI iptal ediyordu — 12 koşuluk bir blok
    #    tamamen bu yüzden çöpe gitti."
    #   O yüzden gerçek sınır BAŞLANGIÇ AYRIMINA GÖRELİDİR:
    #       sınır = max(BEKCI_SPAWN_MAX_M, ilk_ayrım + BEKCI_SPAWN_PAY_M)
    #   normal doğuş (ayrım 40-100 m) -> 600 m, kaçağı hızlı yakalar
    #   uzak doğuş  (ayrım 900 m)     -> 1300 m, meşru yaklaşmayı kesmez
    BEKCI_SPAWN_PAY_M  = _f("DOW_B_SPAWN_PAY", 400.0)
    BEKCI_DONMA_S      = _f("DOW_B_DONMA", 4.0)   # telemetri bu kadar donarsa
    BEKCI_ESIK         = 3                        # ardışık ihlal -> iptal

    # ================= TEMAS SINIFLANDIRMASI =================
    # Kullanıcı isteği (2026-08-23): "drone hedefin pervanesine çarparsa bu
    # vuruş sayılmıyor, drone geriye itiliyor; sen bu pervaneye çarpmayı
    # anla ve bunu vuruş say."
    #
    # ⭐ EŞİK ÖLÇÜLDÜ (TEMAS kampanyası, 6 koşu, döngü hızında ~43 Hz):
    #     koşu  en_yakin  temas ivmesi  @menzil   normal uçuş p99
    #       1     0.78 m     536 m/s²    1.15 m        63
    #       2     0.95 m     879 m/s²    1.11 m        77
    #       3     0.69 m      14 m/s²    5.78 m        59   <- temas YOK
    #       4     0.71 m     359 m/s²    1.19 m        69
    #       5     0.86 m     813 m/s²    1.21 m        67
    #       6     0.93 m      99 m/s²    5.65 m        67   <- temas YOK
    #   Temas darbeleri 359-879, temassızlar 14-99, normal uçuş p99 ≈ 67.
    #   Boşluk ÇOK GENİŞ; eşik 200 (temassızın 2 katı, temasın yarısından az).
    #   Temas menzili 1.11-1.21 m'de KÜMELENİYOR — Talon kanat yarı açıklığı
    #   0.86 m + drone yarıçapı ile geometrik olarak da uyuşuyor.
    #
    # ⚠ BU BİR ÖLÇÜT DEĞİŞİKLİĞİDİR. Eski `isabet` yalnız "menzil < 4 m"
    #   diyordu ve TEMAS ile YAKIN GEÇİŞİ ayırmıyordu (aynı 6 koşuda altısını
    #   da isabet sayardı; gerçekte 4 temas, 2 yakın geçiş, 0 imha).
    #   Bu tarihten önceki kampanyaların `isabet` sayıları bu ölçütle
    #   DOĞRUDAN KIYASLANAMAZ.
    TEMAS_IVME_ESIK = _f("DOW_TEMAS_IVME", 200.0)   # m/s²
    TEMAS_MENZIL_M  = _f("DOW_TEMAS_MENZIL", 2.0)   # m

    # ================= KAYIT =================
    KAYIT_AKTIF   = _b("DOW_KAYIT", True)
    KAYIT_ARALIK  = _f("DOW_KAYIT_ARALIK", 0.5)   # s; kare + telemetri

    # ================= DÖNGÜ =================
    LOOP_HZ = _f("DOW_LOOP_HZ", 50.0)


# ⛔ `CANLI` SÖZLÜĞÜ SİLİNDİ (2026-08-23, §5.12).
#   Panelin kaydırıcıları kullanıcı isteğiyle kaldırılınca ("o slidebarları
#   kaldır, ayarları değiştirme işi sende") bu sözlüğü OKUYAN kod da gitti;
#   geriye 18 satırlık ölü tablo kaldı ve içinde ARTIK OLMAYAN alanlar vardı
#   (MERKEZ_FREN). Ölü kod tutmak arşiv değil borçtur.

# Panel ve kampanya AYRI SÜREÇLER; panelden seçilen kip bu dosyayla taşınır.
_KIP_DOSYA = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".gudum_kipi")
_kip_onbellek = {"t": 0.0, "v": None}


def kip_yaz(k):
    try:
        with open(_KIP_DOSYA, "w") as f:
            f.write(k)
    except Exception:
        pass


def kip_oku(ttl=0.25):
    """Panelden seçilen kipi oku (TTL ile önbellekli — her tik disk okumaz)."""
    import time as _t
    simdi = _t.time()
    if _kip_onbellek["v"] is not None and simdi - _kip_onbellek["t"] < ttl:
        return _kip_onbellek["v"]
    v = Ayar.GUDUM_KIPI
    try:
        with open(_KIP_DOSYA) as f:
            x = f.read().strip().lower()
        if x in ("hibrit", "gps", "gorsel"):
            v = x
    except Exception:
        pass
    _kip_onbellek.update({"t": simdi, "v": v})
    return v

