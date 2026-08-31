# -*- coding: utf-8 -*-
"""
================================================================================
GÖRSEL GÜDÜM (IBVS) — Gazebo yasası, DoW sabitleriyle
================================================================================
YAPI AYNEN TAŞINDI (Seçenek A): saf takip + kutu boyutundan PI hız yasası.
DEĞİŞEN yalnız SABİTLER; hepsi DoW'da ÖLÇÜLDÜ.

TERİMLER (CLAUDE.md §0.2 — hiçbiri tanımsız bırakılmaz)
  * IBVS (görüntü-tabanlı görsel servolama): kontrol hatası doğrudan
    GÖRÜNTÜ UZAYINDA tanımlanır (piksel), 3B konum kestirmeye gerek yok.
  * saf takip (pure pursuit): hız vektörünü her an hedefe DOĞRU çevir.
    Basit ve dayanıklı; kusuru, kaçan hedefte "kuyruktan" takip etmesi.
  * LOS (görüş hattı): araçtan hedefe giden doğru.
  * kapanma hızı: menzilin azalma hızı (−dR/dt).
  * lead (öngörü): nişanı hedefin gideceği yöne ÖNE almak.
  * PI: Oransal + İntegral kontrolcü. P anlık hatayla, I birikmiş hatayla
    orantılı çıktı üretir; I kalıcı hatayı (sabit fark) kapatır.

YARIŞMA KURALI (CLAUDE.md §10) — YAPISAL GARANTİ
  Bu modülün girdileri: bbox pikselleri + KENDİ IMU'muz (roll/pitch/yaw).
  Hedefin GPS'i FONKSİYON İMZASINDA YOK -> görsel fazda kural ihlali
  yapısal olarak İMKÂNSIZ (Gazebo'daki B5 bekçisinin emsali).

DoW'DA ÖLÇÜLEN SABİTLER (Gazebo değeri -> DoW değeri, neden)
  MENZIL_C   296.8 px·m @640  ->  997 px·m @1920
      Gazebo hedefi 1.28 m kanatlıydı, DoW Talon'u 1.718 m. 1920'ye
      ölçeklenmiş Gazebo sabiti 557 olurdu -> 1.79 KAT yanlış.
  V_HUCUM    18.0 m/s -> 28.0 m/s
      DoW Talon'u 17.98 m/s uçuyor. 18 ile kapanma 0.02 m/s = ASLA
      yakalayamayız. Araç 34.6 m/s yapabiliyor; 28 -> kapanma ~10 m/s.
      (Tavanın tamamı kullanılmadı: toplam hız bütçesi dikeyle paylaşılıyor.)
  kamera     FX=166.6/CX=320 @640 -> f=540.4/CX=960 @1920, TILT 26.5°
      Ölçüldü, artık 2.6 px. Ayrıntı: dow/gorus/kamera.py
  VZ tavanı  ±15 simetrik -> +33.5 / -6.95 ASİMETRİK
      Ölçüldü. Simetrik varsaymak alçalma komutunu ~5 kat abartır.

⭐ YAPISAL UYUM: aracın dikey asimetrisi (güçlü tırmanma, zayıf alçalma)
   güdümün ihtiyacıyla ÖRTÜŞÜYOR. Kamera 26.5° YUKARI baktığı için hedefi
   kadrajda tutmak aracı hedefin ALTINDA tutar; oradan hedefe gitmek
   TIRMANMAKTIR — bol yetkimiz olan yön. Gazebo'daki "alttan vuruş"
   tasarımı DoW aracına tesadüfen değil, doğal olarak oturuyor.
================================================================================
⛔⛔ 2026-08-22 — ÜÇ EKLEMEM GERİ ALINDI. DÜRÜST KAYIT:

Görsel fazda hedefi vuramayınca üst üste "iyileştirme" ekledim ve HER BİRİ
işi KÖTÜLEŞTİRDİ. Ölçülen en yakın menzil medyanı:

  GV02  dikey kadraj regülasyonu (yalnız)   12.05 m   ISABET 1/4  <- EN İYİ
  GV03  + lead                              13.75 m   isabet 0/3
  GV04  + merkez freni                      13.00 m   isabet 0/3
  GV06  + sakin kamera                      16.08 m   isabet 0/3
  GV07  + tam yaw bandı + lead 0.5         ~19    m   isabet 0/2

HATAM: her kararı n=3 koşuyla verdim. CLAUDE.md §5.4 tam bunu yasaklıyor
("n<4 iken hüküm cümlesi kurulmaz") ve üç kez yaşandığı yazılı. Sakin
kameranın tespit kazancı (+5.7 puan) gerçek olabilir ama İSABETE
dönüşmedi; kalan ikisi için elimde kazanç gösteren hiçbir veri yok.

GERİ DÖNÜŞ: GV02 yapılandırması (yalnız dikey kadraj regülasyonu) TABAN
kabul edilir; n>=6 ile doğrulanır; sonra her ekleme AYRI ve DÖNÜŞÜMLÜ
A/B ile, n>=4/kol sınanır. Kod duruyor, anahtarlar KAPALI.
================================================================================
"""
import math
import os

from dow.gorus import kamera as KAM


def _fi(ad, v):   # env ile geçersiz kılınabilir (kampanya kill-switch'i)
    return float(os.environ.get(ad, v))


def _b_i(ad, v):
    return os.environ.get(ad, str(int(v))).strip() not in ("0", "", "false", "False")


def _kirp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class IbvsCfg:
    # --- hız yasası ---
    V_HUCUM       = 28.0    # m/s; hücum hızı tavanı (hedef 17.98 -> kapanma ~10)
    V_MIN         = 0.0     # m/s; asla geri gitme
    HUCUM_MENZIL_M= 1.0     # m; PI'nın sıfır noktası = TEMAS menzili.
                            # "Şu menzilde dur" noktası YOK -> hata hep pozitif
                            # kalır, hız tavanda oturur, sabit kapanma.
    K_FWD         = 0.35    # (m/s)/px; P kazancı  (Gazebo'dan AYNEN)
    K_I           = 0.04    # (m/s)/(px·s); I kazancı (Gazebo'dan AYNEN)
    I_MAX         = 8.0     # m/s; integral doyumu (windup önleyici)

    # --- yaw ---
    K_YAW         = 1.0     # tam düzeltme (Gazebo'dan AYNEN)

    YAW_RATE_MAX  = 120.0   # °/s. Araç 214 yapabiliyor AMA hızlı yaw
                            # görüntüyü bulandırıp dedektörü kırar -> KORUNDU.
    YAW_OLU_BAND  = 1.0     # °; altında yaw komutu güncellenmez

    # ⭐ MENZİL ÖLÇÜSÜ: "max" (kutunun uzun ekseni) | "kosegen" (köşegen)
    #
    # NEDEN SORU: menzil, benzer üçgenlerden `R = C/ölçü` ile çıkıyor ve bu
    #   ölçünün MENZİLDEN BAŞKA HİÇBİR ŞEYE bağlı olmaması gerekiyor. Ama
    #   hedef YATTIĞINDA kanat açıklığının kadraja izdüşümü kısalıyor.
    #   ÖLÇÜLDÜ (KREG24+KILIT16, 12750 tespit karesi) — ölçü×R sabit KALMALI:
    #        yatış      max(w,h)·R    köşegen·R
    #        düz            951          1005
    #        8-20°          913 (-4%)     974 (-3%)
    #        20-32°         847 (-11%)    911 (-9%)
    #        >32°           845 (-11%)    985 (-2%)   <- köşegen ÇOK daha iyi
    #   Yani hedef sert yatışa girdiğinde `max(w,h)` menzili %18 şişiriyor;
    #   güdüm "daha uzaktayım" sanıp tam gaz veriyor. Köşegende şişme %7.
    #
    # ⚠ DAHA ÖNCE DENENDİ VE GERİ ALINDI (kullanıcı, 2026-08-27): "menzil
    #   ölçüsünün köşegene geçilmesinin çok bir etkisi yokmuş". O ölçüm DÜZ
    #   uçuştaydı ve orada gerçekten fark YOK (yukarıdaki ilk satır). Fark
    #   yalnız YATIKTA çıkıyor; bu yüzden bu kez `kademeli` senaryosunda,
    #   yani tasarım zarfının içinde sınanıyor (§5.13).
    #
    # ⭐⭐ VARSAYILAN "kosegen" YAPILDI — 2026-08-28, KULLANICI ONAYIYLA.
    #   KAMPANYA KOS24 (24 uçuş, n=6/kol/senaryo, dönüşümlü, tek değişken):
    #     kademeli   KİLİT 0/6 -> 6/6 · KİLİTLİ VURUŞ 0/6 -> 6/6
    #                erken temas 6 -> 0 · en iyi 10 s 1.73 s -> 5.97 s
    #                vuruş sınıfı ŞANS 6/6 -> KONTROLLÜ 5/6
    #     duz        KİLİT 6/6 = 6/6 · KİLİTLİ VURUŞ 6/6 = 6/6  (BOZULMA YOK)
    #   Mekanizma sütunu (algılanan/gerçek menzil), hedefin yatışına göre:
    #     yatış <8°   max 1.039   köşegen 1.052
    #     yatış >32°  max 1.149   köşegen 1.055   <- şişmenin 2/3'ü kesildi
    #   Bağımsız ikinci araç (araclar/kilit_olcu.py, ham cikarim.csv'den
    #   şartname ölçütünü sıfırdan uygulayan) BİREBİR aynı sonucu verdi.
    #
    # ⛔ GERİ DÖNÜŞ: DOW_MENZIL_OLCU=max  (davranış bit bit eski hâl, bekçi B71)
    MENZIL_OLCU   = os.environ.get("DOW_MENZIL_OLCU", "kosegen").strip().lower()

    #   ⭐ 4.0'a YÜKSELTİLDİ — ama YALNIZ K_CY 0.014'e düşürüldüğü için.
    #     Tek başına 4.0 (K_CY 0.06 ile) B8'de KAYBETMİŞTİ; ikisi birlikte
    #     kanalı oransal yapıyor. Bkz. K_CY notu.
    VZ_TAVAN_GORSEL = _fi("DOW_VZ_TAVAN_GORSEL", 4.0)   # m/s

    # --- DİKEY: KADRAJ REGÜLASYONU ("alttan vuruş") ---
    # ⛔ ÖNCEKİ YASA ÇÖKTÜ (GV01, 3 koşu, ölçüldü):
    #   Hız vektörü doğrudan hedefe nişanlanıyordu (saf takip). Bu, hedefin
    #   İRTİFASINA TIRMANMAK demek: 24° yükselişte 28·sin(24°)=11.4 m/s
    #   tırmanma komutu. 6.8 m'lik farkı 0.6 s'de kapatıp hedefin hizasına
    #   çıkıyor; kamera 26.5° YUKARI baktığı için oradan hedef GÖRÜNMÜYOR.
    #   Sonuç: görsel fazda tespit %90 -> %12-15, isabet 0/3.
    #
    # YENİ YASA: hedefi KADRAJDA sabit bir yükseklikte tut (cy -> cy_ref).
    #   Kamera gövdeye sabit ve TILT° yukarı baktığı için "hedefi kadrajın
    #   şurasında tut" demek, "hedefin ALTINDA şu açıyla kal" demektir —
    #   geometri kendiliğinden çıkar, ayrıca hesaplamaya gerek yok.
    #   GİRDİ YALNIZ PİKSEL: menzil/irtifa/GPS KULLANILMAZ.
    #
    #   cy > cy_ref  -> hedef kadrajda AŞAĞIDA -> biz YÜKSEKTEYİZ -> ALÇAL
    #   cy < cy_ref  -> hedef kadrajda YUKARIDA -> biz ALÇAKTAYIZ -> TIRMAN
    # ⭐⭐ YENİDEN AYARLANDI 2026-08-23 (E1+E1b, havuzlanmış n=8/kol)
    #   ⛔ TEŞHİS: K_CY=0.06 + tavan 1.5 ile |e_cy|>25 px olan HER kare
    #     doyuma giriyordu. ÖLÇÜLDÜ: taze kutuda bile karelerin %98.3'ü
    #     doyumda, |e_cy| medyan 143 px. Yani dikey kanal oransal kontrolcü
    #     DEĞİL, AÇ-KAPA anahtarıydı: hedef 30 px de üstte olsa 300 px de
    #     olsa komut aynı (throttle tam tıpatıp 0.019 ölçüldü).
    #     Geometri de tutmuyordu: 24.8° yükseliş + 3.62 m/s kapanma ->
    #     gereken dikey 1.67 m/s, tavan 1.50 m/s.
    #   ⚠ Önceki tavan taramalarım (2/4/8) YANILTICIYDI: hepsinde K_CY 0.06
    #     sabitti, yani hepsi aç-kapaydı; büyük tavan sadece daha büyük
    #     darbe verip salınım üretti. KAZANÇ ve TAVAN hiç BİRLİKTE
    #     değiştirilmemişti — eksik olan deney buydu.
    #      ölçüt              0.06/1.5   0.014/4.0
    #      TEMAS                6/8        8/8
    #      en_yakin medyan     0.86 m     0.51 m   (-%41)
    #      tespit%             59.00      70.80
    #      cx dönüş/s           0.30       0.10   (3 kat sakin)
    #      roll p90             3.75°      3.25°
    #      görsel kesinti      10.20 s     2.05 s (5 kat az)
    #      DOYUM oranı         %97.0      %17.7   <- mekanizma kanıtı
    #   Doğrusal kaldığı aralık: 4.0/0.014 = ±286 px (eskiden ±25 px).
    K_CY          = _fi("DOW_K_CY", 0.014)  # (m/s)/px
    CY_REF_UZAK   = 470.0   # px; UZAKTA hedefi merkezin ÜSTÜNDE tut (altta kal)
    CY_REF_YAKIN  = 540.0   # px; YAKINDA merkeze getir (nişan al, vur)
    # Geçiş kutu boyutuyla: kutu bu değerden büyükse "yakın" sayılır.
    CY_GECIS_PX_UZAK = 40.0   # px (≈25 m)
    CY_GECIS_PX_YAKIN= 90.0   # px (≈11 m)
    VZ_MAX_TIRMAN = 33.5    # m/s; ÖLÇÜLDÜ
    VZ_MAX_ALCAL  = 6.95    # m/s; ÖLÇÜLDÜ (⚠ 4.8 kat asimetrik; hover'da.
                            #   İleri uçuşta 15.6'ya çıkıyor ama tabanı alıyoruz)

    # T6 · DİKEY YUMUŞATMA — |throttle| tespiti en çok bozan büyüklüktü
    #   (2.2 kat). VZ_TAVAN_GORSEL zaten var ama YALNIZ SAKIN_KAMERA
    #   açıkken uygulanıyordu; bu anahtar onu bağımsız kılar.
    # ⭐⭐ GİRDİ 2026-08-23 gecesi — GECENİN EN BÜYÜK KAZANIMI.
    #   B7, n=4/kol, dönüşümlü A/B:
    #      ölçüt          KAPALI     AÇIK
    #      isabet          3/4        4/4
    #      en_yakin       3.00 m     0.72 m
    #      koşular   2.16·1.55·3.84·5.14   0.69·0.82·0.56·0.76
    #      tespit%        20.70      50.90   (2.5 KAT)
    #      doğru%         89.20      95.05
    #      yanlış%        10.80       4.95
    #      görsel faz     27.15 s    38.40 s
    #      roll p90       12.60°      5.55°
    #   ARALIKLAR HİÇ ÖRTÜŞMÜYOR: kontrol [1.55-5.14], deney [0.56-0.82].
    #   İlan edilen birincil ölçüt (tespit%) +30 PUAN; her geçerlilik eşi
    #   de aynı yönde -> kazanç junk kutudan gelmiyor.
    #   MEKANİZMA: kamera GÖVDEYE SABİT. Dikey komut throttle'ı sıçratıyor,
    #   araç dikeyde savruluyor ve 70 px'lik hedef bulanıklaşıyor. İlk
    #   oturumda ölçülmüştü: |throttle| 0.300 (tespit VAR) / 0.669 (YOK) —
    #   2.2 kat, ölçülen EN BÜYÜK ayırıcı. Tavan tam o büyüklüğü kısıyor.
    VZ_TAVAN_AKTIF = _b_i("DOW_VZ_TAVAN", True)

    # ⛔ D1 TERMİNAL DİKEY SERBESTLİĞİ ELENDİ ve SİLİNDİ (2026-08-23)
    #   Hipotez: dikey tavan (1.5 m/s) son metrelerde düzeltmeyi kısıtlıyor.
    #   ÖLÇÜLDÜ (n=4/kol, dönüşümlü) — HİPOTEZ ÇÜRÜDÜ, aralıklar AYRIK:
    #       ölçüt        kapalı                 açık (menzil<5 m'de serbest)
    #       TEMAS         4/4                    0/4
    #       en_yakin   0.78 m (0.89·0.80·        1.61 m (1.70·1.85·
    #                          0.76·0.70)                1.53·1.17)
    #   Mekanizma kapısı geçmişti (terminal kare 13-20 vs 0), yani özellik
    #   çalıştı ve İŞİ KÖTÜLEŞTİRDİ. Dikey tavan terminali KISITLAMIYOR,
    #   KORUYOR: kalkınca araç son metrelerde savruluyor.
    # T5 · BBOX KÖPRÜSÜ (ölü-hesap) — ⭐ GİRDİ (B2, n=4/kol)
    #   Çıkarım 10 Hz; aradaki ~100 ms'de ve tespit boşluklarında güdüm
    #   BAYAT kutuyla çalışıyor. Kutunun ATALET yönünü saklayıp KENDİ
    #   dönüşümüzü telafi ederek kutuyu kadrajda ileri taşırız.
    #   ⭐ GİRDİ YALNIZ: son kutu + KENDİ IMU'muz. GPS YOK, menzil YOK.
    #      ölçüt            KOPRU=0    KOPRU=0.5
    #      isabet             1/4        4/4
    #      en_yakin medyan   5.44 m     1.94 m   (-64%)
    #      roll p90          48.65°     27.05°   (-44%)
    #   Süre TARANDI (B5, n=4/kol): 0.3 -> 3.35 m, 0.5 -> 1.90 m,
    #   1.0 -> 1.34 m (kazanan). 2.0 ek kazanç vermedi (B6).
    KOPRU_S       = _fi("DOW_KOPRU_S", 1.0)

    # B · BAYAT KUTUYU BIRAK — BERABERE, KAPALI (C1, n=4/kol)
    #   Köprü KOPRU_S dolunca güdüm sessizce ESKİ HAM KUTUYA düşüyordu;
    #   kaybı ancak 20 çıkarım (=2 s) sonra kabul ediyordu. ÖLÇÜLDÜ:
    #   kutu yaşı medyan 80 ms, p90 1546 ms, max 2187 ms — karelerin %30'u
    #   0.5 s'den ESKİ kutuyla uçuyor. Mekanizma kapısı GEÇTİ (bayat_birak
    #   sayacı deney kolunda 46-497, kontrolde 0).
    #      ölçüt            kapalı   açık
    #      TEMAS             3/4      3/4
    #      en_yakin medyan  0.92 m   0.75 m  (-%18; ilan edilen eşik %20)
    #   Aralıklar örtüşüyor -> GİRMEDİ. ⚠ Karşılaştırmanın tamamı hedef DÜZ
    #   uçarken yapıldı; hayalete uçmanın bedeli manevrada çıkabilir.
    #   Anahtar KAPALI, gerekçesi yazılı, manevra açılınca yeniden sınanacak.
    BAYAT_BIRAK   = _b_i("DOW_BAYAT_BIRAK", False)

    # ⛔ D2 TAM KERTERİZ — GÜDÜM ÇEVRİMİNDE ELENDİ, ÖLÇÜMDE GİRDİ (2026-08-23)
    #
    #   `piksel_kerteriz` roll döndürmesini TILT eklendikten SONRA uyguluyor;
    #   yükseliş bileşeni 26.5° olduğu için küçük yatış bile azimuta
    #   26.5·sin(roll) sızdırır. Hata ≈ roll'un kendisi kadar
    #   (3°->3.3°, 10°->11.0°, 35°->39.8°).
    #   Gazebo'nun `los_seviye`si dönüşü 3B ışın üzerinde doğru sırayla
    #   yapıyor; AYNEN taşındı + tersi yazıldı (gidiş-dönüş 700/700 tam).
    #
    #   ⭐ HANGİSİ DOĞRU: 4146 eşleşmiş karede tespit edilen kutuya uyum
    #      yaklaşık 33.1 px / TAM 13.6 px medyan sapma -> TAM zincir DOĞRU.
    #      Bu yüzden ÖLÇÜM YOLU tam zincire geçirildi (kosu.py, tespit_olcu).
    #
    #   ⛔ AMA GÜDÜM ÇEVRİMİNDE ELENDİ (havuzlanmış n=8/kol):
    #        temas 6/8 -> 4/8,  cx dönüş/s 0.34 -> 1.30 (4 kat salınım)
    #      SEBEP: tam zincirde araç 35° yatıkken KADRAJ MERKEZİNDEKİ hedefin
    #      azimutu +21° çıkar (doğrudur). Güdüm bunu `yaw + 3.0·azimut` ile
    #      hız yönüne çeviriyor -> yatış > büyük yaw > daha çok yatış.
    #      Kazançlar YANLIŞ modele göre ayarlanmış.
    #   ⛔ Yalnız köprüde denendi (D2c): temas 3/4 vs 3/4, BERABERE.
    #      D2'deki "+11 puan tespit" büyük ölçüde kısa/yakın karşılaşmanın
    #      yan etkisiymiş (§5.2 tuzağı).
    #
    #   ⚠⚠ BİLİNEN BORÇ: güdüm hâlâ MATEMATİKSEL OLARAK YANLIŞ kerterizi
    #      kullanıyor. Şu an zararsız çünkü roll p90 3-8°'ye indi (gece
    #      başında 42-51°'ydi). Yatış tekrar büyürse hata sessizce geri
    #      gelir. Doğru çözüm: tam zincire geçip K_YAW'ı yeniden ayarlamak.
    #      Bekçi B29 bu borcu görünür tutuyor.
    # D3 · DİKEY YASA — Gazebo'nun 3B saf takibi vs kadraj regülasyonu
    #   Kullanıcı: "gazebodaki görsel güdüm algoritmasının aynısını entegre
    #   etsek olmaz mı." Yatay kanal ZATEN aynı; kalan tek büyük fark bu.
    #
    #   "kadraj"   (mevcut): vz = -K_CY·(cy - cy_ref)
    #        Hedefi kadrajda sabit yükseklikte tut. GV01'de saf takip
    #        dikeyde "hedefin irtifasına tırmanıp kaybetme" yapınca buna
    #        geçmiştim — AMA O KARARI n=3 İLE VERMİŞTİM (§5.4 ihlali).
    #   "saftakip" (Gazebo): nisan_elev = K_ELEV·elev_los;
    #        vz = -v·sin(nisan_elev), yani hız vektörü 3B'de hedefe nişanlanır
    #        (yatayla AYNI matematik). Artı:
    #          - türev sönümlemesi K_VZ_D (kendi dikey hızımız nişanı aşarsa
    #            komut geri çekilir -> hedefin üstünden geçme biter)
    #          - |v| KORUNUMU: dikey ne alırsa yatay kısılır
    #        elev_los TAM zincirden gelir (los_seviye) — D2'de ölçüldü,
    #        4146 karede 2.4 kat daha uyumlu.
    #   ⚠ Gazebo'nun YAVASLA / lead / DIKEY_KAPANMA özellikleri DAHİL DEĞİL
    #     (ayrı deney). Dikey tavan HER İKİ KOLDA da uygulanır.
    DIKEY_YASA    = os.environ.get("DOW_DIKEY_YASA", "kadraj").strip()
    K_ELEV        = _fi("DOW_K_ELEV", 1.0)      # Gazebo değeri
    K_VZ_D        = _fi("DOW_K_VZ_D", 0.6)      # Gazebo değeri

    # T4 · YERELLİK KAPISI — düşük eşik + "hedef nerede olmalı" kısıtı.
    #   Görsel fazda hedefin kadrajda NEREDE olduğunu bir önceki kutumuzdan
    #   (ve T5 köprüsünden) biliyoruz. O yüzden dedektör eşiğini düşürüp
    #   (0.40 -> YEREL_CONF_MIN) adayları YERELLİKLE eleyebiliriz:
    #     - merkez, beklenen yerin YEREL_KAPI_PX + 2*son_kutu içinde
    #     - genişlik, son genişliğin 0.5-2.0 katı
    #   Kazanç: 0.40 eşiğinin ALTINDA kalan soluk tespitler kurtarılır
    #   (ölçüldü: eşik 0.10'da tespit %49 / 0.40'ta %40 — 9 puan orada).
    #   Yanlış-pozitif riski: argmax'ı OSD çalıyordu; yerellik bunu keser.
    #   ⭐ TAMAMEN KAMERA İÇİ — GPS yok (§10).  0 = kapalı.
    # ⭐ GİRDİ 2026-08-23 gecesi — B3b+B3c havuzlanmış, n=5/kol, dönüşümlü:
    #      ölçüt          YEREL=0    YEREL=60
    #      isabet          4/5        5/5
    #      en_yakin       1.84 m     1.87 m   (berabere)
    #      tespit%        28.00      25.00    (aralıklar İÇ İÇE: 20-43 vs
    #                                          23-31 -> AYIRT EDİLEMİYOR)
    #      doğru%         74.50      79.70
    #      yanlış%        25.50      20.30
    #      kadraj%        96.40     100.00
    #      roll p90       31.60°      8.30°   (-74%; 5 koşunun 4'ü ≤9.3)
    #   İlan edilen birincil ölçüt (tespit%) FARK GÖSTERMEDİ; zaten kapı
    #   açıkken "tespit" tanımı değişiyor (dedektör buldu VE yerellikten
    #   geçti), yani kollar arası aynı şeyi ölçmüyor. Ölçüt sonradan
    #   değiştirilmedi (§5.6) — ayırt edemediği söylendi. Kalan HER ölçüt
    #   tek yönde. CLAUDE.md §4: salınan araç, aynı sonucu üretse bile kötüdür.
    #   ⚠ İlk uygulamam ELENMİŞTİ (B3: isabet 1/4, görsel faz 4.85 s):
    #     kapı bir kez kaybedince kilitleniyordu. YEREL_KURTAR ve "en yüksek
    #     güvenli" seçim kuralı bunu çözdü.
    YEREL_KAPI_PX = _fi("DOW_YEREL_KAPI", 60.0)
    YEREL_CONF_MIN = _fi("DOW_YEREL_CONF", 0.20)
    # ⛔ KİLİTLENME ÇARESİ (B3'te ölçüldü): referans bayatlayınca hiçbir aday
    #   kapıdan geçmiyor, kapı asla yeniden yakalayamıyor ve görsel faz
    #   ~5 s'de düşüyordu (tespit %33 -> %15-18, isabet 2/2 -> 0/4).
    #   Bu kadar ardışık başarısızlıktan sonra kapı AÇILIR ve düz argmax'a
    #   dönülür; ilk yeni tespit referansı tazeler.
    YEREL_KURTAR  = 5

    # --- geçerlilik ---
    # ⛔ LEAD (kestirim payı) İKİNCİ KEZ ELENDİ — 2026-08-26, §5.12 ile SİLİNDİ.
    #   Ö-E (kare, n=4/3)  : birincil ölçüt değişmedi (imha 0/4 vs 0/3)
    #   Ö-F (kaçamak, n=4/4): HER ÖLÇÜTTE KÖTÜLEŞTİ —
    #        kaçırma 3 -> 5 · ilk denemede 2/4 -> 0/4 · süre 20.4 -> 24.9 s
    #        görsel tespit %65.5 -> %51.1 · salınım cx 0.58 -> 1.23
    #   GV03'ün (2026-08-22, n=3) hükmü DOĞRUYMUŞ; o red yöntemsel olarak
    #   zayıftı ama sonucu tuttu. Bu kez doğru zarfta ve n=4/kol ölçüldü.
    #   ⚠ Ö-E'de "lead salınımı düşürdü" diye okumuştum (cx 1.13 -> 0.66);
    #     Ö-F tersini gösterdi (0.58 -> 1.23). O düşüş koşu değişkenliğiymiş.
    #   Bekçi B20 `LEAD_*` adlarını yeniden YASAKLI listeye aldı.

    # ⭐ Ö-G · DÖNÜŞTE YAVAŞLA — 2026-08-26
    #
    # YAPISAL EKSİK (koddan çıkarıldı, 2026-08-26):
    #   hedef_boyut = MENZIL_C/HUCUM_MENZIL = 997/1.0 = 997 px
    #   hata = 997 - kutu (tipik 40-150 px) -> v_istek = 0.35*900 ~ 315 m/s
    #   -> V_HUCUM'a (28) kırpılıyor. Hız ancak kutu 917 px olunca düşer,
    #      bu da 1.1 m menzil demek. YANİ GÖRSEL FAZ BOYUNCA HIZ DAİMA
    #      TAVANDA. Güdüm hızı dönüş kabiliyetiyle HİÇ takas etmiyor.
    #
    # NEDEN ÖNEMLİ (§5.11 — "salınım sandığın şey fizik olabilir"):
    #   R = V^2/(g·tan θ). Ölçüldü (KD1 daire, GORSEL fazı): hız 21.8 m/s,
    #   yatış p90 31.7° -> dönüş yarıçapı ~78 m. Hedefin dairesi 17.5 m.
    #   Hızı 0.55 katına indirmek yarıçapı 0.30 katına indirir (~24 m).
    #
    # YASA: nişan hatası büyükken hızı kıs, düz bacakta tam hız.
    #   kesme = 1 - (1 - YAVASLA_TABAN) * min(1, |eps_yaw| / YAVASLA_ACI)
    #   v = v * kesme
    #   eps_yaw=0   -> kesme=1.00 (düz bacakta TAM HIZ)
    #   eps_yaw>=25 -> kesme=YAVASLA_TABAN
    #
    # ⚠ §5.13 TASARIM ZARFI: bu bir "yayda yavaşla, düz kesimde hızlan"
    #   çevrimidir. `daire`de düz kesim YOKTUR -> çevrimin ikinci yarısı
    #   gerçekleşemez ve araç KALICI yavaş kalır (§5.10'daki Ö11 tuzağı).
    #   Bu yüzden KAZANIM `kare`de ölçülür, REGRESYON `daire` ve `taban`da.
    #
    # ⚠ YAVASLA_TABAN = 1.0 VARSAYILAN -> hiç kısma yok, BİT BİT aynı.
    # Açma: DOW_YAVASLA=0.55  (kapatma: 1.0)
    YAVASLA_TABAN = _fi("DOW_YAVASLA", 1.0)    # hızın alt katsayısı
    YAVASLA_ACI   = _fi("DOW_YAVASLA_ACI", 25.0)   # tam etki açısı (°)
    # ⭐ ÖLÜ BANT — Ö-G'nin ölçülmüş kusurunun çaresi (2026-08-26 gecesi).
    #   Ö-G'de kesme karelerin %83.7'sinde uygulandı (medyan 0.909): yasa
    #   "keskin köşede yavaşla" değil "neredeyse her zaman biraz yavaşla"
    #   olarak çalıştı. Görüş +22 puan kazandı ama kapanma öldü
    #   (en yakın 5.12 -> 5.87 m, dört çiftin dördünde kontrol önde).
    #   Ölü bant: nişan hatası bu eşiğin ALTINDAYKEN kesme HİÇ uygulanmaz,
    #   böylece düz bacakta TAM HIZ korunur.
    #   0 = ölü bant yok (Ö-G'deki davranış).
    YAVASLA_OLU   = _fi("DOW_YAVASLA_OLU", 0.0)    # ölü bant (°)

    # ⛔ İKİ AYRI EŞİK — karıştırılmasın:
    #     YEREL_CONF_MIN (0.20) : dedektörün TARAMA eşiği. Kutular burada
    #                             bulunur; düşük tutulur ki yerellik
    #                             süzgeci eleyebilsin.
    #     CONF_MIN       (0.40) : KABUL kapısı. Tarama bulsa bile buradan
    #                             geçemezse güdüme girmez.
    #
    #   0.40 SİM MODELİYLE (talon_v3) ÖLÇÜLDÜ:
    #       eşik 0.10 -> tespit %49, argmax doğru %43  (yanlış-pozitif çalıyor)
    #       eşik 0.40 -> tespit %40, argmax doğru %40  (fark KAPANIYOR)
    #       eşik 0.50 -> tespit %38, argmax doğru %38
    #   Yani 9 puan tespit karşılığında sahte kilit tamamen bitiyor.
    #
    #   ⚠ GERÇEK MODELDE (tayarti_v1) HENÜZ ÖLÇÜLMEDİ. İlk ölçümler
    #     gerçek Talon'da 0.746 ve 0.887 verdi — eşiğin epey üstünde.
    #     Uçuş kaydındaki `ham_sebep` sütunu "conf" redlerini sayar;
    #     çok çıkarsa eşik GERÇEK ÖLÇÜMLE düşürülür:
    #         DOW_CONF_MIN=0.30 ./baslat_drone.sh --gorsel
    CONF_MIN      = _fi("DOW_CONF_MIN", 0.40)
    BOYUT_MIN_PX  = _fi("DOW_BOYUT_MIN_PX", 8.0)   # küçük kutu güvenilmez
    MENZIL_MAX_M  = 50.0    # m; ötesinde görsel devir YOK (tespit %10)
    MENZIL_MIN_M  = 3.0     # m; ALTINDAKİ kutu = dev yanlış-pozitif.
                            # 997/3 = 332 px'lik kutu demek; hedef bu boyuta
                            # ancak TEMAS anında ulaşır. Dedektör 140 m'de
                            # bu boyutta kutular üretiyordu (ölçüldü).

    # ⭐ Ö-A · TERMİNAL SÜREKLİLİK İSTİSNASI (2026-08-25)
    #
    # SORUN (ölçüldü, KAMERA10 n=5, 859 çıkarım):
    #     menzil    tespit%   gecerli() reddi
    #     0-3 m      %22.0        %38.0
    #     3-6 m      %73.6         %0.0
    #   Uçurum tam MENZIL_MIN_M sınırında. Yani vuruşun son yarım
    #   saniyesinde güdümü KENDİ SÜZGECİMİZ kör ediyor. Yo-yo'yu tetikleyen
    #   üç seriden biri (k01 @ 24.6 s, 2.1 m) doğrudan bu.
    #
    # NEDEN SÜZGEÇ SİLİNMİYOR: sebebi meşru. Dedektör 140 m'de dev
    #   yanlış-pozitif üretiyor, kutudan hesaplanan menzil 1.3 m çıkıyor,
    #   güdüm "temas" sanıp tam hücum veriyor ve araç yere çakılıyor
    #   (2026-08-21, iki koşu, "Player ☠"). Silmek o çakılmayı geri getirir.
    #
    # AYIRT EDİCİ FİZİK: dev yanlış-pozitif YOKTAN var olur; gerçek hedef
    #   BÜYÜYEREK gelir. 140 m'de aniden beliren 400 px sahtedir; 200 px'ten
    #   400 px'e büyüyen gerçektir. İstisna bu sürekliliği arar:
    #     (a) son KABUL EDİLEN kutu taze mi        (yaş <= KOPRU_S)
    #     (b) yeni kutu ondan en fazla kaç kat büyük (<= TERMINAL_BUYUME)
    #   İkisi de sağlanmazsa eski davranış AYNEN geçerli.
    #
    # ⛔ GPS YOK: koşulun iki girdisi de piksel/zaman (§10 temiz).
    # Geri dönüş: DOW_TERMINAL=0
    TERMINAL_AKTIF   = _b_i("DOW_TERMINAL", True)
    TERMINAL_BUYUME  = _fi("DOW_TERMINAL_BUYUME", 2.0)   # kat


def olcu(w, h, cfg=IbvsCfg):
    """Kutudan MENZİL ÖLÇÜSÜ ve ona ait sabit. TEK KAYNAK — `komut` ve
    `gecerli` ikisi de burayı kullanır, yoksa biri max biri köşegen
    hesaplayıp menzil kapısı ile güdüm birbirini tutmaz."""
    if cfg.MENZIL_OLCU == "kosegen":
        return math.hypot(w, h), KAM.MENZIL_C_KOSEGEN
    return max(w, h), KAM.MENZIL_C


def komut(cx, cy, w, h, own_yaw_deg, own_pitch_deg, own_roll_deg,
          hiz_I, dt, cfg=IbvsCfg, own_vz=0.0, denge_boyut_px=None,
          reg=None):
    """IBVS kontrol yasası.

    GİRDİ (hedefin GPS'i YOK — yapısal garanti):
      cx, cy, w, h  : tespit kutusu (piksel) — TEK canlı hedef kaynağı
      own_*         : KENDİ yönelimimiz (derece) — kendi IMU'muz
      hiz_I         : hız integralinin o anki değeri (m/s); çağıran taşır
      dt            : adım süresi (s)
      own_vz        : KENDİ dikey hızımız (m/s, yukarı+) — D3 türev
                      sönümlemesi için; kendi sensörümüz (§10 temiz)
      denge_boyut_px: PI'nın DENGE NOKTASI — kutunun oturması istenen
                      boyut (PİKSEL). None ise eskisi gibi
                      MENZIL_C/HUCUM_MENZIL_M (=997 px, temas) kullanılır
                      ve yasa BİT BİT eskisiyle aynıdır.
                      ⭐ KİLİT FAZI bunu ~166 px yapar: araç temasa sürmek
                      yerine kutuyu o boyutta TUTAR, böylece hedef ekranda
                      %6'nın üstünde kalır ve 5 saniyelik kilit birikebilir
                      (Teknofest 6.1.4).
                      ⛔ NEDEN PİKSEL, METRE DEĞİL (§10): bu yasanın
                      girdileri arasında METRİK bir dünya büyüklüğü
                      OLMAMALI. Bir kez "menzil" adında bir sayı imzaya
                      girerse, yarın oraya GPS'ten gelen bir menzil
                      bağlanabilir ve kimse fark etmez. Bekçi B1/B19
                      imzayı ad düzeyinde denetler; ayar metre cinsinden
                      okunur ama piksele çağrı YERİNDE, tek seferde
                      çevrilir (Ayar.KILIT_MENZIL_M -> MENZIL_C/M).

    ÇIKTI: (v_ned, vz, yaw_hedef_deg, hiz_I_yeni, tani)
      v_ned = (vx, vy) m/s DÜNYA yatay düzleminde (NED: x kuzey, y doğu)
      vz    = m/s, NED (POZİTİF = AŞAĞI; çevirici ters çevirir)
    """
    tani = {}

    # --- 1) MENZİL: kutu boyutundan (benzer üçgenler, p = C/R) ---
    boyut, _C = olcu(w, h, cfg)
    # ⭐ BALIKGÖZ DÜZELTMESİ — `C` MERKEZDE kalibre edilir; kadrajın
    #   kenarında aynı cisim farklı piksel kaplar. pinhole modelinde
    #   çarpan 1.0'dır, yani davranış BİT BİT eskisidir.
    _duz = KAM.olcek_duzeltme(cx, cy)
    R = (_C * _duz / boyut) if boyut > 0 else None
    tani["ibvs_boyut_px"] = boyut
    tani["ibvs_fe_duzeltme"] = round(_duz, 4)
    tani["ibvs_menzil_m"] = R if R else -1

    # --- 2) KERTERİZ: kadraj konumundan, KENDİ duruşumuz telafi edilerek ---
    azimut, yukselis = KAM.piksel_kerteriz(cx, cy, own_pitch_deg, own_roll_deg)
    tani["ibvs_azimut"] = azimut
    tani["ibvs_yukselis"] = yukselis

    # --- 4) YAW: burnu hedefe çevir (+ lead) ---
    eps_yaw = azimut
    if abs(eps_yaw) < cfg.YAW_OLU_BAND:
        eps_yaw = 0.0
    yaw_hedef = own_yaw_deg + cfg.K_YAW * eps_yaw
    tani["ibvs_eps_yaw"] = eps_yaw

    # --- 4b) İSTENEN KADRAJ YERİ (dikey nişan) — fren de bunu kullanır ---
    kg = _kirp((boyut - cfg.CY_GECIS_PX_UZAK) /
               max(1e-6, cfg.CY_GECIS_PX_YAKIN - cfg.CY_GECIS_PX_UZAK), 0.0, 1.0)
    cy_ref = cfg.CY_REF_UZAK + kg * (cfg.CY_REF_YAKIN - cfg.CY_REF_UZAK)

    # --- 5) HIZ: kutu boyutu hatası üzerinden PI ---
    # Denge kutusu = TEMAS kutusu -> hata hep pozitif, hız tavanda oturur.
    hedef_boyut = (_C / cfg.HUCUM_MENZIL_M if denge_boyut_px is None
                   else max(1.0, float(denge_boyut_px)))
    hata_px = hedef_boyut - boyut
    if reg is None:
        hiz_I = _kirp(hiz_I + cfg.K_I * hata_px * dt, -cfg.I_MAX, cfg.I_MAX)
        v_istek = cfg.K_FWD * hata_px + hiz_I
        v = _kirp(v_istek, cfg.V_MIN, cfg.V_HUCUM)
    else:
        # ⭐ KİLİT FAZI REGÜLATÖRÜ (dow/gudum/kilit.py · HizRegulatoru).
        #   Nazik P + yükü taşıyan integral + anti-windup + değişim hızı
        #   tavanı. Buradaki PI'ya HİÇ DOKUNULMAZ; `hiz_I` olduğu gibi geri
        #   döner, çünkü TERMİNAL faza geçildiğinde bu PI temiz başlamalı.
        #   ⛔ reg=None iken tek bir satır bile farklı koşmaz (bekçi B68).
        v = reg.hiz(hata_px, dt)
        v_istek = v
        tani["ibvs_kilit_I"] = round(reg.I, 2)          # §5.1 mekanizma
        tani["ibvs_kilit_doyum"] = reg.doyum
        tani["ibvs_kilit_slew"] = reg.slew_kesti

    # ⭐ Ö-G DÖNÜŞTE YAVAŞLA (bkz. IbvsCfg.YAVASLA_TABAN).
    #   YAVASLA_TABAN=1.0 iken kesme=1.0 ve yasa BİT BİT bugünküyle aynı.
    _kesme = 1.0
    if cfg.YAVASLA_TABAN < 1.0:
        # ölü bant: eşiğin altındaki nişan hatasında HİÇ kısma yok
        _fazla = max(0.0, abs(eps_yaw) - cfg.YAVASLA_OLU)
        _genis = max(1e-6, cfg.YAVASLA_ACI - cfg.YAVASLA_OLU)
        _oran = min(1.0, _fazla / _genis)
        _kesme = 1.0 - (1.0 - cfg.YAVASLA_TABAN) * _oran
        v = v * _kesme
    tani["ibvs_kesme"] = round(_kesme, 3)      # §5.1 mekanizma sütunu

    tani["ibvs_hata_px"] = hata_px
    tani["ibvs_denge_px"] = hedef_boyut   # §5.1 mekanizma sütunu
    tani["ibvs_v"] = v

    # --- 6) YATAY: hız LOS (nişan) yönünde ---
    yon = math.radians(yaw_hedef)
    vx = v * math.cos(yon)
    vy = v * math.sin(yon)

    # --- 7) DİKEY ---
    e_cy = cy - cy_ref                      # + = hedef kadrajda AŞAĞIDA
    if cfg.DIKEY_YASA == "saftakip":
        # D3 · GAZEBO: hız vektörünü 3B'de hedefe nişanla (yatayla aynı
        # matematik). elev_los TAM zincirden; nişan ofseti YOK.
        _, _elev = KAM.los_seviye(cx, cy, own_roll_deg, own_pitch_deg)
        nisan_elev = _kirp(cfg.K_ELEV * _elev, -60.0, 60.0)
        _vz_nisan = v * math.sin(math.radians(nisan_elev))     # yukarı+
        # TÜREV SÖNÜMLEMESİ: kendi dikey hızımız nişanı aştıysa geri çek
        vz_yukari = _vz_nisan + cfg.K_VZ_D * (_vz_nisan - own_vz)
        tani["ibvs_nisan_elev"] = nisan_elev
    else:
        # KADRAJ REGÜLASYONU (mevcut): hedefi kadrajda sabit yükseklikte tut
        vz_yukari = -cfg.K_CY * e_cy        # aşağıdaysa ALÇAL
    _v0 = vz_yukari
    if cfg.VZ_TAVAN_AKTIF:                              # T6
        vz_yukari = _kirp(vz_yukari, -cfg.VZ_TAVAN_GORSEL, cfg.VZ_TAVAN_GORSEL)
    # §5.1 MEKANİZMA SÜTUNU: dikey kanal DOYUMDA mı? Ölçüldü 2026-08-23:
    #   taze kutuda bile karelerin %98.3'ü doyumda -> kontrolcü oransal
    #   DEĞİL, aç-kapa. Bu sütun kazanç/tavan çiftinin işe yarayıp
    #   yaramadığını doğrudan gösterir.
    tani["ibvs_vz_kirpildi"] = int(_v0 != vz_yukari)
    vz_yukari = _kirp(vz_yukari, -cfg.VZ_MAX_ALCAL, cfg.VZ_MAX_TIRMAN)
    if cfg.DIKEY_YASA == "saftakip":
        # |v| KORUNUMU: dikey ne aldıysa gerisi yataya (Gazebo).
        _yat = math.sqrt(max(v * v - vz_yukari * vz_yukari, 0.0))
        vx = _yat * math.cos(yon); vy = _yat * math.sin(yon)
    vz_ned = -vz_yukari            # NED: pozitif = AŞAĞI
    tani["ibvs_vz_yukari"] = vz_yukari
    tani["ibvs_cy_ref"] = cy_ref
    tani["ibvs_e_cy"] = e_cy
    tani["ibvs_yakinlik"] = kg

    return (vx, vy), vz_ned, yaw_hedef, hiz_I, tani


def gecerli(cx, cy, w, h, conf, cfg=IbvsCfg, son_w=None, son_yas=None):
    """Bu tespit güdüme girebilir mi? (§5.1 mekanizma kapısı için ayrı tutuldu)

    ⭐ GÜVEN EŞİĞİ TAKİPÇİ AÇIKKEN DEĞİŞİR (2026-08-24).

    Takipçinin TÜM FİKRİ şudur: zayıf kutuyu tek karede eşikle atmak yerine,
    KARELER ARASI TUTARLILIKLA süzmek. Dedektör bu yüzden 0.10'da koşuyor.
    Ama burada 0.40 eşiğini TEKRAR uygulamak, takipçinin yaşattığı her zayıf
    kutuyu alt akışta öldürür — yani özelliği kendi tasarım zarfının DIŞINDA
    sınamış oluruz (§5.13).

    ÖLÇÜLDÜ (duman testi, 30 kare): takipçi 19 kutu döndürdü (3 eşleşme +
    16 öngörü), `gecerli()` bunların 14'ünü ELEDİ — güdüme yalnız 5'i ulaştı.

    KİMLİK KARARINI TAKİPÇİ VERİR: `TargetLock` kilitlenmek için zaten
    conf >= KILIT_CONF (0.40) arıyor; kilit kurulduktan SONRA izi düşük
    güvenli kutuyla sürdürmek BYTE mantığının ta kendisi. Bu yüzden takipçi
    açıkken eşik TakipCfg.CONF_MIN'e iner.

    ⚠ GEOMETRİK KONTROLLER AYNEN KALIR (boyut, menzil, kadraj) — onlar
    güven değil FİZİK kontrolü; takipçi onları geçersiz kılmaz.

    ⛔ TAKİPÇİ KAPALIYKEN DAVRANIŞ BİT BİT AYNI (bekçi B48)."""
    esik = cfg.CONF_MIN
    try:
        from dow.gorus.tracker import TakipCfg as _TC
        if _TC.AKTIF:
            esik = _TC.CONF_MIN
    except Exception:
        pass
    if conf < esik: return False, "conf"
    boyut, _C = olcu(w, h, cfg)
    if boyut < cfg.BOYUT_MIN_PX: return False, "boyut"
    # ⭐ KAPI da AYNI menzili görmeli — panelde yazan sayı ile kapının
    #   kullandığı sayı ayrışırsa operatör "neden reddetti" diyemez.
    R = (_C * KAM.olcek_duzeltme(cx, cy) / boyut) if boyut > 0 else None
    if R is None or R > cfg.MENZIL_MAX_M: return False, "menzil_uzak"
    if R < cfg.MENZIL_MIN_M:
        # ⭐ Ö-A TERMİNAL SÜREKLİLİK İSTİSNASI — bkz. IbvsCfg.TERMINAL_AKTIF.
        #   son_w / son_yas verilmezse (None) davranış ESKİSİYLE BİT BİT AYNI;
        #   bekçi B52 bunu sınar.
        _surekli = (cfg.TERMINAL_AKTIF and son_w and son_yas is not None
                    and son_yas <= cfg.KOPRU_S
                    and boyut <= cfg.TERMINAL_BUYUME * son_w)
        if not _surekli:
            return False, "menzil_yakin"                # dev yanlış-pozitif
        return True, "terminal"     # §5.1 mekanizma: istisna DEVREYE GİRDİ
    if not (0 <= cx < KAM.IMG_W and 0 <= cy < KAM.IMG_H): return False, "kadraj"
    return True, ""
