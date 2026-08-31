# -*- coding: utf-8 -*-
"""
================================================================================
KAMERA YAKALAMA — analog VTX -> USB yakalama kartı
================================================================================
⛔ EN BÜYÜK TUZAK: OPENCV KARE BİRİKTİRİR.
   `cv2.VideoCapture.read()` sürücünün tamponundaki EN ESKİ kareyi verir.
   Yakalama 30 FPS iken biz 10 Hz okursak tampon dolar ve gördüğümüz kare
   saniyelerce GERİDE kalır. Güdüm için bu ölümcül: 20 m/s'de 1 saniyelik
   gecikme 20 metredir.
   ÇARE: ayrı bir iş parçacığı SÜREKLİ `grab()` yapar ve yalnız EN SON
   kareyi tutar. Okuyan taraf her zaman en tazesini alır.
   Ayrıca CAP_PROP_BUFFERSIZE=1 denenir (her sürücü desteklemez).

⚠ ANALOG VİDEO BEKLENTİSİ:
   PAL 720x576 / NTSC 720x480, gürültülü, tarama çizgili, senkron kaybında
   kısmi kare. Model 1920x1080 oyun görüntüsüyle eğitildi; ölçek ve doku
   FARKLI. Bu, tespit başarımını doğrudan etkiler ve ÖLÇÜLMELİDİR.

⚠ KİLİT ÖLÇÜTÜ ÇÖZÜNÜRLÜKTEN BAĞIMSIZDIR (şartname oran veriyor: AV kutusu
   %25/%10 kırpma, hedef ekranın %5'i). Yani 720x576'da da aynen geçerli;
   yalnız `dow/gorus/kamera.py` sabitleri (F_PX, TILT, MENZIL_C) yeniden
   ölçülmelidir — onlar piksel cinsindendir.
================================================================================
"""
import os
import threading
import time


#: Dizüstünün DAHİLİ kamerasını ele veren kart adları. Yakalama kartı
#: tercih edilirken bunlar ELENİR.
#: ⛔ SAHADA GÖRÜLDÜ (2026-08-29): varsayılan indeks 0'dı ve panelde
#:   yakalama kartı yerine DİZÜSTÜNÜN KENDİ KAMERASI görünüyordu.
#:   Ölçülen kurulum: video0/1 = "USB webcam" (Quanta, dahili),
#:   video2/3 = "USB Video" (MacroSilicon MS210x Grabber = EasierCAP).
DAHILI_IPUCU = ("webcam", "integrated", "facetime", "hd camera", "quanta")


class KameraCfg:
    #: "oto" = kendiliğinden bul (VARSAYILAN) · "2" / "/dev/video2" = elle
    KAYNAK   = os.environ.get("DOW_KAM_KAYNAK", "oto")
    GENISLIK = int(os.environ.get("DOW_KAM_W", "0"))     # 0 = sürücü varsayılanı
    YUKSEKLIK = int(os.environ.get("DOW_KAM_H", "0"))
    FPS      = float(os.environ.get("DOW_KAM_FPS", "0"))
    FOURCC   = os.environ.get("DOW_KAM_FOURCC", "MJPG")  # "" = dokunma


def _kart_adi(yol):
    """v4l2 kart adı (sysfs'ten; harici araç gerektirmez)."""
    try:
        n = os.path.basename(yol)
        with open("/sys/class/video4linux/%s/name" % n) as f:
            return f.read().strip()
    except Exception:
        return ""


def cihazlari_tara(kare_dene=True):
    """Bütün /dev/videoN cihazlarını tara. Döner: [{yol, ad, kare, cozunurluk}]

    ⛔ "AÇILDI" YETMEZ, "KARE VERİYOR" GEREKİR. UVC kameralar her biri için
       İKİ düğüm oluşturur (biri görüntü, biri meta veri) ve meta düğümü
       açılır ama kare vermez. Yalnız açılışa bakan bir seçim, sistematik
       olarak yanlış düğümü seçer.
    """
    import cv2
    import glob
    sonuc = []
    for yol in sorted(glob.glob("/dev/video*"),
                      key=lambda y: int("".join(c for c in y if c.isdigit()) or 0)):
        ad = _kart_adi(yol)
        girdi = {"yol": yol, "ad": ad, "kare": False, "cozunurluk": None}
        if kare_dene:
            cap = None
            try:
                cap = cv2.VideoCapture(yol, cv2.CAP_V4L2)
                if cap.isOpened():
                    ok, kare = cap.read()
                    if ok and kare is not None:
                        girdi["kare"] = True
                        girdi["cozunurluk"] = (kare.shape[1], kare.shape[0])
            except Exception:
                pass
            finally:
                if cap is not None:
                    cap.release()
        sonuc.append(girdi)
    return sonuc


def otomatik_bul():
    """Yakalama kartını seç. Döner: (yol, gerekce) ya da (None, sebep).

    SEÇİM KURALI (sırayla):
      1. KARE VEREN cihazlar arasından
      2. adı dahili kamera ipucu İÇERMEYENİ tercih et
      3. eşitlikte en küçük indeks
    """
    cihazlar = cihazlari_tara()
    calisan = [c for c in cihazlar if c["kare"]]
    if not calisan:
        return None, ("hiçbir /dev/video* kare vermiyor (%d cihaz tarandı)"
                      % len(cihazlar))
    harici = [c for c in calisan
              if not any(x in c["ad"].lower() for x in DAHILI_IPUCU)]
    sec = (harici or calisan)[0]
    gerekce = "%s — %s %s%s" % (sec["yol"], sec["ad"] or "?",
                                "%dx%d" % sec["cozunurluk"] if sec["cozunurluk"] else "",
                                "" if harici else "  ⚠ DAHİLİ kamera olabilir")
    return sec["yol"], gerekce


class Kamera:
    """Her zaman EN TAZE kareyi veren yakalayıcı."""

    def __init__(self, cfg=KameraCfg):
        self.cfg = cfg
        self.cap = None
        self.acik = False
        self.hata = None
        self._kare = None
        self._kare_t = 0.0
        self._sayac = 0
        self._kilit = threading.Lock()
        self._calisiyor = False
        self._is = None
        self.n_okunan = 0
        self.n_bos = 0
        self.gerekce = ""
        self.secilen = ""

    def ac(self):
        import cv2
        k = self.cfg.KAYNAK
        self.gerekce = ""
        if str(k).strip().lower() in ("oto", "auto", ""):
            yol, gerekce = otomatik_bul()
            self.gerekce = gerekce
            if yol is None:
                self.hata = ("kamera bulunamadı: %s\n"
                             "   · yakalama kartı takılı mı?  ls /dev/video*\n"
                             "   · elle seç:  DOW_KAM_KAYNAK=/dev/video2" % gerekce)
                return False
            kaynak = yol
        else:
            try:
                kaynak = int(k)
            except ValueError:
                kaynak = k
        try:
            self.cap = cv2.VideoCapture(kaynak, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(kaynak)
            if not self.cap.isOpened():
                self.hata = ("kamera açılamadı: %r. `ls /dev/video*` ve "
                             "`v4l2-ctl --list-devices` ile kontrol et." % k)
                return False
            if self.cfg.FOURCC:
                self.cap.set(cv2.CAP_PROP_FOURCC,
                             cv2.VideoWriter_fourcc(*self.cfg.FOURCC))
            if self.cfg.GENISLIK:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.GENISLIK)
            if self.cfg.YUKSEKLIK:
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.YUKSEKLIK)
            if self.cfg.FPS:
                self.cap.set(cv2.CAP_PROP_FPS, self.cfg.FPS)
            # ⛔ TAMPONU 1'E ZORLA — gecikmenin en büyük kaynağı budur.
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            self.secilen = str(kaynak)
        except Exception as e:
            self.hata = "%s: %s" % (type(e).__name__, e)
            return False
        self.acik = True
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True,
                                    name="kamera")
        self._is.start()
        return True

    def _dongu(self):
        while self._calisiyor:
            ok, kare = self.cap.read()
            if not ok or kare is None:
                self.n_bos += 1
                time.sleep(0.005)
                continue
            self.n_okunan += 1
            with self._kilit:
                self._kare = kare
                self._kare_t = time.monotonic()
                self._sayac += 1

    def son_kare(self):
        """(kare_BGR, yakalama_zamani, sayac) — kare yoksa (None, 0, 0)."""
        with self._kilit:
            if self._kare is None:
                return None, 0.0, 0
            return self._kare, self._kare_t, self._sayac

    def cozunurluk(self):
        k, _, _ = self.son_kare()
        return (0, 0) if k is None else (k.shape[1], k.shape[0])

    def kapat(self):
        self._calisiyor = False
        if self._is:
            self._is.join(timeout=1.0)
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass
        self.acik = False

    def durum(self):
        w, h = self.cozunurluk()
        _, t, s = self.son_kare()
        return {"acik": self.acik, "genislik": w, "yukseklik": h,
                "cihaz": self.secilen, "gerekce": self.gerekce,
                "sayac": s, "yas": round(time.monotonic() - t, 3) if t else -1,
                "okunan": self.n_okunan, "bos": self.n_bos,
                "hata": self.hata}
