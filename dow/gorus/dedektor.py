# -*- coding: utf-8 -*-
"""
================================================================================
DEDEKTÖR — talon_v3.pt (kullanıcının DoW fotoğraflarıyla eğittiği model)
================================================================================
ÖLÇÜLDÜ 2026-08-21, canlı DoW V5.0.0, n=857 kare, EŞLEŞTİRİLMİŞ A/B
(aynı karede iki çözünürlük). "GERÇEK tespit" = kutu, kalibre kamera
modelinin öngördüğü konumun yakınında VE makul boyutta.

  menzil    imgsz=960   imgsz=1920
  25-40 m      %32         %63
  40-60 m       %6         %55
  60-90 m       %0          %9

⭐ imgsz=1920 ZORUNLU. Sebep: 1920x1080 kadraj 960'a küçültülünce hedef
   YARIYA iner; 50 m'de 20 px olan Talon ağın girdisinde 10 px kalır ve
   YOLO'nun tespit sınırının altına düşer.
   BEDEL (fp32): çıkarım 24 -> 60 ms; döngü 17.5 -> 10.8 FPS.
   ⚠ ESKİDEN BURADA "FP16 fayda vermedi" YAZIYORDU — YANLIŞTI, bkz. DetCfg.

KONUM DOĞRULUĞU: tespit edilen kutu, kalibre modelin öngördüğü yere
   1.6-2.5 px içinde düşüyor -> kamera modeli bağımsız DOĞRULANDI.

GÜVEN EŞİĞİ (1920'de tarandı):
  eşik 0.10 -> tespit %49, argmax doğru %43   (yanlış-pozitif argmax'ı çalıyor)
  eşik 0.40 -> tespit %40, argmax doğru %40   (fark KAPANIYOR)
  eşik 0.50 -> tespit %38, argmax doğru %38
  SEÇİM 0.40: ~9 puan tespit karşılığında yanlış-pozitifin en yüksek güveni
  çalmasını tamamen bitirir. Güdüm menzili bilmediği için argmax'a mecburdur.

⚠ GÖRSEL DEVİR MENZİLİ <= 50 m. 60-90 m'de tespit %9 — orada GPS fazı sürer.
⚠ Tespit %55-63; kesintiler VAR.

⛔ HybridSORT TAKİPÇİSİ ÇIKARILDI (2026-08-22, kullanıcı kararı):
  "şu an detection kötü olduğu için tracking bir işe yaramıyor ve rastgele
   yerlere track atabiliyor, o yüzden gerek yok şu anda hybridsort'a.
   düzgün detection modeli gelince tekrardan entegre edebiliriz."
  Takipçi, dedektörün YANLIŞ-POZİTİFİNİ de bir iz olarak benimseyip Kalman
  ile 20 kare boyunca İLERİ TAŞIYORDU; yani hatayı silmiyor, uzatıyordu.
  Kod `dow/gorus/tracker.py` olarak depo tarihçesinde duruyor (commit b435f08).
================================================================================
"""
import os
import time

import numpy as np

# ⭐ MODEL SEÇİMİ (2026-08-24). v5 = OSD hard-negatif + uzak uçak fotoğrafları
# eklenmiş veri setiyle eğitildi (dataset_det_v5, 30 epoch, aynı mimari YOLO11s).
# ÖLÇÜLDÜ — 300 UZAK hedefli kare (<32 px, >31 m), düz argmax, conf 0.40,
# yani KAPI YOKMUŞ GİBİ:
#            hedefte   OSD'de   baska   kutu yok
#     v3      %17.0     %1.0    %19.3    %62.7
#     v5      %22.7     %0.7    %22.3    %54.3
# -> uzak tespit belirgin daha iyi; OSD zaten %1'di, %0.7'ye indi.
# Geri dönüş: DOW_MODEL=talon_v3
# ⛔ VARSAYILAN talon_v5 -> talon_v3'E DÖNDÜ (2026-08-24, ÖLÇÜMLE).
#
# KULLANICI GÖZLEMİ: "önceden detection bu kadar iyi değilken hedef aracı çok
# daha iyi vurduğumuz zaman vardı... direkt 20 saniyede falan, ama şu an full
# kaçıyor." DOĞRU ÇIKTI.
#
# KAMPANYA MAB (n=4/kol, tek değişken model, dönüşümlü, düşen koşu yok):
#     model     imha    süre (koşu koşu)        en yakın   devir@
#     talon_v3  4/4     27, 34, 34, 14 s        0.43 m     10.6 s
#     talon_v5  3/4     65, 65, 18, 100 s       0.94 m     13.9 s
#   -> v3 İKİ KAT hızlı öldürüyor ve İKİ KAT yakın geçiyor.
#
# MEKANİZMA — ANGAJMAN BANDINDA TESPİT (görsel fazda, kutu yaşı < 0.3 s):
#     menzil    v3 (n=274)   v5 (n=810)
#     4- 8 m      %87-91       %55-74
#     8-15 m      %88-93       %73-85
#   v5 UZAĞI iyileştirmek için eğitildi (hard negatif + uzak uçak fotoğrafı)
#   ve orada gerçekten daha iyi. Ama BİZİM VURUŞUMUZ 4-15 m'de oluyor ve
#   orada v3 açık ara önde. Zincir: v5 terminalde temas kaybediyor ->
#   GÖRSEL'den ISTASYON'a 2 KAT sık düşüyor (medyan 2 vs 1) -> devirden
#   vuruşa 20 s yerine 51 s -> koşuların üçte biri hiç vuramıyor.
#
# ⛔ ÇÜRÜTÜLEN ÜÇ HİPOTEZ (hepsi ölçüldü, hiçbiri sebep değil):
#   1. "v5 yanlış yere kutu atıyor"  -> GERÇEK tespit v3 %76 / v5 %95: v5 DAHA DOĞRU
#   2. "v5'in kutu ölçeği kaymış"    -> kutu/beklenen 0.976 vs 0.957: %2, ihmal
#   3. "hedef farklı davranıyor"     -> hız/manevra/irtifa tüm oturumlarda AYNI
#   Güdüm de değişmemiş: istasyon hatası ve devir menzili iki dönemde de aynı.
#
# ⛔⛔ talon_v5 SİSTEMDEN TAMAMEN SİLİNDİ (2026-08-27, §5.12) — KULLANICI KARARI.
#   Yukarıdaki ölçüm kaydı DURUYOR (silinen özelliğin kararı kaybolmaz), ama
#   ağırlık dosyası, çalışma-anı model değiştirme kapısı (`DetCfg.MODEL` +
#   `_model_uygula`) ve model A/B araçları koddan ÇIKARILDI.
#
#   ⚠ NEDEN ÇIKARILMAK ZORUNDAYDI — §5.12'nin tarif ettiği hata BİREBİR yaşandı:
#     model adı İKİ ayrı yerde tanımlıydı ve varsayılanları FARKLIYDI
#     (`MODEL_YOLU` -> talon_v3, `DetCfg.MODEL` -> talon_v5). Dedektör kuruluşta
#     v3'ü yüklüyor, İLK ÇIKARIMDA model-değişti kapısı devreye girip sessizce
#     v5'e geçiyordu. 24 Ağustos'ta v5 ELENDİĞİ HÂLDE 27 Ağustos'a kadar bütün
#     uçuşlar v5 ile koştu. Kapı, MODEL20 kampanyasının dönüşümlü koşu şartı
#     (§4) için yazılmıştı; kampanya bitince kaldırılmadı.
#     -> Elenen özellikten kalan artık, üç gün boyunca her ölçümün altını oydu.
#
#   Artık model YALNIZ kuruluşta, TEK yerden seçilir; çalışma anında değişmez.
# ⛔⛔ YOL ÇALIŞMA DİZİNİNDEN BAĞIMSIZ OLMALI (30 Ağu 2026'da yakalandı).
#   Eskiden göreli yazılıydı: "modeller/<ad>.pt". `baslat_drone.sh`
#   çalışma dizinini `reel/` yapıyor ve model orada DEĞİL, depo kökünde.
#   Sonuç: dedektör HİÇ yüklenmiyordu, "görsel KAPALI" satırı akıp
#   gidiyordu ve ekranda hiç kutu çıkmıyordu. Depoyu kökten çalıştıran
#   testlerde sorun görünmüyordu — en sinsi hata türü.
_DOW_KOK = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))          # .../dow/gorus/dedektor.py -> kök


def _model_yolu():
    ad = os.environ.get("DOW_MODEL", "talon_v3")
    acik = os.environ.get("DOW_MODEL_YOL")        # tam yol vermek isteyene
    if acik:
        return acik
    return os.path.join(_DOW_KOK, "modeller", "%s.pt" % ad)


MODEL_YOLU = _model_yolu()

# ============================================================================
#  ⭐ ÇÖZÜNÜRLÜK DİKİŞİ (2026-08-29) — gerçek kamera için
#
#  ⛔ AŞAĞIDAKİ SAYILAR 1920x1080 KADRAJDA ÖLÇÜLDÜ. Gerçek FPV zinciri
#    640x480 veriyor. İkisi arasındaki fark, "imgsz" sayısının ANLAMINI
#    değiştiriyor:
#
#      1920x1080 kaynakta  imgsz=1920 -> ölçek 1.0  (NATİF piksel)
#       640x480  kaynakta  imgsz=1920 -> ölçek 3.0  (BÜYÜTME, yeni bilgi YOK)
#
#    Yani simdeki "1920, 960'ı yener" bulgusu aslında "NATİF çözünürlük,
#    KÜÇÜLTMEYİ yener" demekti. 640 genişlikte kaynakta bunun sadık
#    karşılığı imgsz=640'tır; 1920 kullanmak 8.3 KAT yavaşlatır
#    (ölçüldü RTX 4060, 640x480 kare: 5.3 ms -> 44.0 ms).
#
#  Aynı şey YAKIN_ESIK_PX için de geçerli: 55 px, 1920 genişlikte ölçüldü.
#  640 genişlikte AYNI fiziksel hedef 3 kat küçük görünür -> eşik ~18 px.
#
#  ⛔ VARSAYILANLAR DEĞİŞMEDİ. Hiçbir DOW_DET_* verilmezse simülasyonda
#    ölçülmüş davranış BİREBİR korunur. Gerçek kamera değerleri
#    `reel/baslat_drone.sh` içinde verilir.
# ============================================================================
def _f(k, v):
    x = os.environ.get(k)
    if x is None or x.strip() == "":
        return float(v)
    try:
        return float(x)
    except ValueError:
        raise ValueError("%s='%s' sayı değil" % (k, x))


IMGSZ_UZAK  = int(_f("DOW_DET_IMGSZ_UZAK", 1920))
#   ÖLÇÜLDÜ (1920x1080): 960 kullanmak 40-60 m'de tespiti %56 -> %7 düşürür
IMGSZ_YAKIN = int(_f("DOW_DET_IMGSZ_YAKIN", 960))
#   yakında hız kazanmak için (24 ms vs 60 ms)
CONF_MIN    = _f("DOW_DET_CONF", 0.40)
#   ÖLÇÜLDÜ: argmax'ı yanlış-pozitiften korur
# ⛔ `DEVIR_MENZIL_M` BURADAN SİLİNDİ (2026-08-25, §5.12): ölü sabitti,
#   hiçbir güdüm kodu okumuyordu. Görsel devrin GERÇEK menzil tavanı
#   `ibvs.IbvsCfg.MENZIL_MAX_M` (50 m) — `gecerli()` orada uyguluyor.
#   Kamera kapısının TEK emniyet tavanı odur; bekçi B10 onu sınar.

# UYARLANABİLİR ÇÖZÜNÜRLÜK EŞİĞİ — bir ÖNCEKİ karenin kutu genişliğine bakar.
# Kutu bu değerden BÜYÜKSE hedef zaten iri demektir; 960 yeterli olur ve
# döngü 10.8 -> 17.5 FPS'e çıkar.
#
# EŞİK ÖLÇÜLDÜ — tahmin DEĞİL. Yakın menzil koşusu, n=788 kare, EŞLEŞTİRİLMİŞ
# (aynı karede iki çözünürlük de koşuldu):
#
#     kutu px   menzil    n     960    1920   kazanan
#     15- 22     54 m    227     %6     %87    1920
#     22- 30     38 m    284    %39     %69    1920
#     30- 40     28 m    107    %67     %89    1920
#     40- 55     21 m    126    %59     %78    1920
#     55- 75     15 m     39    %92     %90    960   <- GEÇİŞ NOKTASI
#     75-110     11 m      5    %40     %40    (n yetersiz)
#
# 55 px'in ALTINDA 1920 açık ara kazanıyor (54 m'de %6 -> %87, 14 kat).
# 55 px'in ÜSTÜNDE ikisi eşitleniyor (%92 vs %90) ama 960 1.6 KAT HIZLI
# -> terminal fazda (menzil <18 m, kapanma hızlı) tepki süresi kazanılır.
YAKIN_ESIK_PX = _f("DOW_DET_YAKIN_ESIK", 55.0)   # ÖLÇÜLDÜ (≈18 m menzil)
#   ⚠ 1920 GENİŞLİKTE ölçüldü. 640 genişlikte aynı hedef 3 kat küçüktür.


# ⛔ `half` ULTRALYTICS 8.4'TE KULLANIMDAN KALKTI ve her çıkarımda
#   uyarı basıyor. 130 FPS'te bu, konsolu saniyede yüzlerce satırla
#   dolduruyor ve AÇILIŞ TEŞHİSLERİNİ boğuyor — sahada bilgi kaybı.
#   ÖLÇÜLDÜ (30 Ağu 2026, RTX 4060, 640x480): fp32 5.3 ms · "fp16" 5.2 ms
#   -> bayrak ZATEN İŞE YARAMIYOR. Destekleniyorsa geçilir, değilse
#   HİÇ geçilmez; davranış aynı, gürültü biter.
def _half_destekli():
    try:
        import inspect
        from ultralytics.engine.model import Model as _M
        return "half" in inspect.signature(_M.predict).parameters
    except Exception:
        return False


try:
    import warnings as _w
    _w.filterwarnings("ignore", message=".*'half' is deprecated.*")
except Exception:
    pass

HALF_GECERLI = _half_destekli()


def _b(k, v):  return os.environ.get(k, str(int(v))).strip() not in ("0","","false","False")
def _i(k, v):  return int(float(os.environ.get(k, v)))


class DetCfg:
    """CANLI ayarlar — SINIF nitelikleri. Güdüm döngüsü her karede okur,
    panel uçuş sırasında değiştirebilir (CLAUDE.md §6).

    FP16 — 16 bit kayan nokta
    ------------------------
    Ağırlıklar ve ara hesaplar 32 yerine 16 bitle tutulur. Ekran kartının
    "tensor core" birimleri 16 bitte iki kat iş yapar.
    ÖLÇÜLDÜ 2026-08-23, 140 kare, EŞLEŞTİRİLMİŞ (aynı kareler):
        fp32 imgsz1920: 30.6 ms | gerçek tespit %80.0
        fp16 imgsz1920: 19.1 ms | gerçek tespit %79.3     <- 1.6 KAT
    ⛔ Bu dosyanın ESKİ başlığında "FP16 fayda vermedi" yazıyordu — YANLIŞTI.
      O ölçüm oyun çalışırken (GPU paylaşımlıyken) alınmış olmalı.
    ⛔ ONNX Runtime (CUDA sağlayıcı, fp16) AYNI karelerde 38.0 ms — PyTorch
      fp16'nın İKİ KATI. ONNX ELENDİ, modeller/*.onnx üretilmedi bırakıldı.

    PENCERE_PX — natif yerel pencere (ROI)
    --------------------------------------
    Kaynak kadraj 1920x1080; imgsz=1920 dendiğinde ultralytics uzun kenarı
    1920'ye ölçekler -> ölçek katsayısı TAM 1.0. Yani ağa ZATEN natif piksel
    gidiyor, sadece 1088'e dolgu var. O hâlde hedefin etrafından PxP natif
    kare kesmek hedefin PİKSELLERİNİ DEĞİŞTİRMEZ; yalnız taranan alanı
    P²/(1920·1088) kadar küçültür (640 icin 1/5.1).
    ÖLÇÜLDÜ 2026-08-23, eşleştirilmiş, truth-doğrulamalı, 120 kare/bant:
        bant           TAM1920   KIRP640
        <25px (>40m)     %15.0     %12.5
        25-40 (25-40m)   %20.8     %25.0
        40-70 (14-25m)   %81.7     %81.7
        >70px  (<14m)    %50.0     %50.0
      -> kalite AYNI, süre 30.6 -> 5.7 ms.
    ⛔ PENCERE BOYUTU REJİME GÖRE SEÇİLİR — ÖLÇÜLDÜ 2026-08-23 (HZ ilk
      çevrimi, §5.1 mekanizma kapısı): görsel fazda hedef iri olduğu için
      uyarlanabilir kural zaten imgsz=960 seçiyor. 960 letterbox 960x544 =
      522 bin piksel; 640 pencere 410 bin. Yani BUGÜNKÜ tabana karşı kazanç
      yalnız 1.28 kat -> uçuşta det_ms 19.9 -> 19.6, yani HİÇ.
      5.4 katlık kazanç imgsz=1920'ye karşıydı ve o yalnız UZAK menzilde
      devreye giriyor. Bu yüzden pencere, mevcut YAKIN_ESIK_PX kuralına
      oturtuldu:
          kutu >= 55 px (yakın): 960 letterbox -> 448 natif  (2.6 kat)
          kutu <  55 px (uzak) : 1920          -> 640 natif  (5.1 kat)
      Her iki boyut da kendi bandında tam kadrajla EŞİT ölçüldü
      (448: %82.5 vs %81.7 ve %49.2 vs %50.0).

    ⚠ Pencere merkezi `dow/ana.py::_yerel_bul` içindeki `ref`tir: köprüyle
      KENDİ dönüşümümüz telafi edilmiş son kutu. Girdi yalnız kamera + kendi
      IMU'muz — GPS YOK (§10 temiz).

    ISKA_TAM — pencere ıskalarsa AYNI tikte tam kadraja düş
    -------------------------------------------------------
    Bu kapı sayesinde tespit oranı taban koldan KÖTÜ OLAMAZ: pencere bir şey
    bulursa hızlıyız, bulamazsa zaten tam kadraj koşuyoruz. Bedel yalnız
    ıska karelerinde (~3 ms fazla).
    """
    # ⛔ `MODEL` BURADAN SİLİNDİ (2026-08-27, §5.12): ikinci bir model
    #   varsayılanıydı ve `MODEL_YOLU` ile ÇELİŞİYORDU; ayrıntı dosya başında.
    # ⭐ FP16 AÇILDI (2026-08-25). ÖLÇÜLDÜ (talon_v3, 40 gerçek kare, oyun
    #   KAPALI, ayrı süreçlerde — `araclar/motor_olc.py`):
    #       .pt fp32   28.6 ms   (35.0 FPS)   <- eski varsayılan
    #       .pt fp16   18.6 ms   (53.7 FPS)   1.54 KAT, kutular AYNI
    #   Doğruluk bedeli YOK: aynı karelerde kutulu kare ve güven eşit
    #   (fp32 conf 0.657 / fp16 0.659).
    #   ⚠ TUZAK: `predict(half=True)` ultralytics predictor kurulduktan
    #     SONRA SESSİZCE YOK SAYILIR. Bu yüzden `_hassasiyet_uygula()`
    #     modelin gerçek hassasiyetini AutoBackend üzerinden değiştirir ve
    #     `_fp16` sütunu §5.1 mekanizma kanıtı olarak loglanır.
    #   Geri dönüş: DOW_FP16=0
    FP16          = _b("DOW_FP16", True)
    PENCERE_PX    = _i("DOW_PENCERE_PX", 0)        # UZAK rejim; 0 = KAPALI
    PENCERE_YAKIN = _i("DOW_PENCERE_YAKIN", 448)   # YAKIN rejim (kutu>=55px)
    ISKA_TAM      = _b("DOW_PENCERE_ISKA_TAM", True)


class Dedektor:
    """Uyarlanabilir çözünürlüklü dedektör.
    Önceki karenin kutu boyutuna bakarak bu karenin imgsz'sini seçer:
    büyük kutu (yakın hedef) -> 960 (hızlı), küçük kutu (uzak) -> 1920 (duyarlı).
    Kutu yoksa DAİMA 1920 (hedefi kaybetmişken duyarlılık şart)."""

    def __init__(self, yol=MODEL_YOLU, conf=CONF_MIN, uyarlanabilir=True,
                 yakin_esik_px=YAKIN_ESIK_PX):
        from ultralytics import YOLO
        self.m = YOLO(yol); self.conf=conf
        self.uyarlanabilir = uyarlanabilir
        self.yakin_esik = yakin_esik_px
        self._son_w = 0.0
        self._isindi = False
        self.son_imgsz = IMGSZ_UZAK      # teşhis: hangi kolda çalıştık
        self.son_pencere = 0             # §5.1 mekanizma: 0 = tam kadraj
        self.son_ms = 0.0                # §5.1 mekanizma: tarama süresi
        self.pencere_say = 0; self.tam_say = 0; self.iska_tam = 0
        self.son_ham = None              # GÖSTERİM — güdüm okumaz
        self.son_ham_n = 0               # GÖSTERİM — kaç aday vardı
        self._fp16 = False               # modelin O ANKİ gerçek hassasiyeti

    def isit(self, img):
        for iz in (IMGSZ_YAKIN, IMGSZ_UZAK):
            for _ in range(2):
                self.m.predict(img, imgsz=iz, conf=self.conf,
                               verbose=False,
                               **({"half": DetCfg.FP16} if HALF_GECERLI else {}))
        self._isindi = True

    def _imgsz_sec(self):
        if not self.uyarlanabilir: return IMGSZ_UZAK
        # kutu yoksa (son_w=0) DAİMA duyarlı kol
        return IMGSZ_YAKIN if self._son_w >= self.yakin_esik else IMGSZ_UZAK

    # ⛔ `_model_uygula` BURADAN SİLİNDİ (2026-08-27, §5.12): MODEL20
    #   kampanyasının dönüşümlü koşusu için yazılmış çalışma-anı model
    #   değiştirme kapısıydı; kampanya bitti, elenen modeli sessizce geri
    #   yüklüyordu. Model artık YALNIZ `__init__`'te seçilir.

    def _hassasiyet_uygula(self):
        """⛔ FP16 BAYRAĞINI GERÇEKTEN UYGULA — yoksa kol SAHTE kalır.

        YAŞANDI 2026-08-23 (ve muhtemelen 2026-08-21'de de): `predict(...,
        half=True)` ultralytics predictor'ı BİR KEZ kurulduktan sonra
        YOK SAYILIYOR. Model `torch.float32` kalıyor, süre değişmiyor.
        Mekanizma kapısı (§5.1) yakaladı: uçuşta det_ms 19.9 -> 20.6, yani
        HİÇ hızlanma yok. Çevrimdışı tezgâhta çalışmasının sebebi orada her
        kol için YENİ bir YOLO nesnesi kurulmasıydı.

        DOĞRU YOL — ikisi BİRDEN gerekir:
          1) ağırlıkları dönüştür (`.half()` / `.float()`)
          2) `AutoBackend.fp16` bayrağını çevir — GİRDİ tensörünün tipi
             `predictor.preprocess` içinde buna bakılarak seçilir; yalnız
             ağırlığı çevirmek tip uyuşmazlığı hatası verir.
        """
        ist = bool(DetCfg.FP16)
        if ist == self._fp16: return
        pr = getattr(self.m, "predictor", None)
        ab = getattr(pr, "model", None) if pr is not None else None
        if ab is None: return                      # predictor henüz kurulmadı
        ab.half() if ist else ab.float()
        ab.fp16 = ist
        if hasattr(pr, "args"): pr.args.half = ist
        self._fp16 = ist

    def _cikar(self, im, imgsz, conf, x0=0, y0=0):
        """Bir görüntüyü tara; kutuları TAM KADRAJ koordinatında döner.

        ⭐ TOPLU AKTARIM (2026-08-24, yer-kontrol `model-fps` branch'inden).
        ESKİDEN: `for b in r.boxes: b.xyxy[0].tolist(); float(b.conf)` —
        her kutu için BEŞ ayrı GPU->CPU aktarımı. Her aktarım örtük bir
        `cuda.synchronize()` demek: CPU, GPU'nun o ana kadarki TÜM işini
        bitirmesini bekler ve bu sırada Python'un GIL'ini (global kilidi)
        bırakıp geri alır. conf=0.10'da tipik 8-15 kutu -> kare başına
        40-75 gidiş-dönüş; hepsi doğrudan `det_ms`'e biner.
        ŞİMDİ: xyxy ve conf TEK SEFERDE numpy'a alınır, döngü CPU'da döner.

        ÇIKTI BİT BİT AYNI — aynı tensörden aynı float'lar okunuyor,
        yalnız aktarım sayısı değişiyor (tests/test_dow.py B43 bunu sınar)."""
        r = self.m.predict(im, imgsz=imgsz, conf=conf,
                           verbose=False,
                           **({"half": DetCfg.FP16} if HALF_GECERLI else {}))[0]
        b = r.boxes
        if b is None or len(b) == 0:
            return []
        xy = b.xyxy.cpu().numpy() if hasattr(b.xyxy, "cpu") else np.asarray(b.xyxy)
        cf = b.conf.cpu().numpy() if hasattr(b.conf, "cpu") else np.asarray(b.conf)
        out = []
        for i in range(len(xy)):
            a1, b1, a2, b2 = (float(xy[i][0]), float(xy[i][1]),
                              float(xy[i][2]), float(xy[i][3]))
            out.append(((a1+a2)/2.0 + x0, (b1+b2)/2.0 + y0,
                        a2-a1, b2-b1, float(cf[i])))
        return out

    def _tara(self, img, conf, merkez):
        """PENCERE varsa oradan, yoksa/ıskalarsa TAM KADRAJDAN tarar.

        Teşhis (§5.1 mekanizma sütunu):
          son_pencere : bu karede kullanılan pencere kenarı (0 = tam kadraj)
          son_ms      : bu karenin toplam tarama süresi (ms)
        """
        if not self._isindi: self.isit(img)
        self._hassasiyet_uygula()          # §5.1: bayrak GERÇEKTEN uygulansın
        t0 = time.perf_counter()
        # REJİM SEÇİMİ — `_imgsz_sec` ile AYNI eşik (`_son_w` vs YAKIN_ESIK).
        P = int(DetCfg.PENCERE_PX)
        if P > 0 and self._son_w >= self.yakin_esik:
            P = int(DetCfg.PENCERE_YAKIN) or P
        H, W = img.shape[:2]
        if P > 0 and merkez is not None and P <= min(W, H):
            x0 = int(min(max(merkez[0] - P/2.0, 0), W - P))
            y0 = int(min(max(merkez[1] - P/2.0, 0), H - P))
            alt = np.ascontiguousarray(img[y0:y0+P, x0:x0+P])
            kutular = self._cikar(alt, P, conf, x0, y0)
            self.pencere_say += 1
            if kutular or not DetCfg.ISKA_TAM:
                self.son_pencere = P
                self.son_ms = (time.perf_counter() - t0) * 1000.0
                self._ham_kaydet(kutular)
                return kutular
            self.iska_tam += 1          # pencere boş -> AYNI tikte tam kadraj
        iz = self._imgsz_sec()
        self.son_imgsz = iz
        kutular = self._cikar(img, iz, conf, 0, 0)
        self.tam_say += 1
        self.son_pencere = 0
        self.son_ms = (time.perf_counter() - t0) * 1000.0
        self._ham_kaydet(kutular)
        return kutular

    def _ham_kaydet(self, kutular):
        """⭐ GÖSTERİM İÇİN — MODELİN HAM ÇIKTISI, hiçbir süzgeçten
        geçmemiş hâli. GÜDÜM BUNU OKUMAZ.

        NİYE: `_yerel_bul` adayları YERELLİKLE eliyor, `gecerli()` menzil
        ve boyutla eliyor. İkisi de haklı — ama operatör ekranda HİÇBİR İZ
        göremeyince "model çalışmıyor" sanıyor. 29-30 Ağu 2026'da tam bu
        oldu ve saatler kaybedildi. Model ne gördüyse ekranda GÖRÜNSÜN;
        güdümün onu kabul edip etmediği AYRI bir bilgidir (ayrı renk).
        """
        self.son_ham = (max(kutular, key=lambda k: k[4]) if kutular else None)
        self.son_ham_n = len(kutular)

    def bul(self, img, merkez=None):
        """En yüksek güvenli kutu: (cx, cy, w, h, conf) ya da None.
        ⚠ Menzil BİLİNMEZ -> boyut/konum kapısı UYGULANMAZ; argmax'a mecburuz.
          Bu yüzden CONF_MIN yüksek tutulur (ölçümle seçildi)."""
        kutular = self._tara(img, self.conf, merkez)
        if not kutular:
            self._son_w = 0.0            # kayıpta duyarlı kola DÖN
            return None
        b = max(kutular, key=lambda k: k[4])
        self._son_w = b[2]
        return b

    def bul_hepsi(self, img, conf=None, merkez=None):
        """DÜŞÜK eşikte TÜM kutular: [(cx, cy, w, h, conf), ...].

        NEDEN: `bul()` argmax döner ve argmax yanlış-pozitif olabilir
        (OSD yazısı 0.50 güven alabiliyor). Görsel fazda hedefin NEREDE
        olduğunu KENDİ önceki kutumuzdan biliyoruz; o yüzden eşiği
        düşürüp adayları YERELLİK ile eleyebiliriz. Bu kapı tamamen
        KAMERA içidir — GPS yok (§10)."""
        kutular = self._tara(img, conf or self.conf, merkez)
        self._son_w = max((k[2] for k in kutular), default=0.0)
        return kutular

    def sifirla(self):
        self._son_w = 0.0
