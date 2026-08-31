# -*- coding: utf-8 -*-
"""
================================================================================
VİDEO KAYDI — FPV görüntüsünü dosyaya yaz
================================================================================
⛔ NİYE VAR: yarışma şartnamesi kilitlenmeleri "kaydedilen videolar ve
   yeniden oynatma sistemleri kullanılarak" inceliyor (Haberleşme Dokümanı
   §8). Kilit iddiamızın arkasında görüntü olmalı. Ayrıca uçuş sonrası
   analizde CSV'nin söylemediğini video söyler (CLAUDE.md §2.6: görüntü ile
   log birbirini DOĞRULAR).

⛔ GÜDÜM DÖNGÜSÜNÜ BLOKE ETMEZ. Kendi iş parçacığında koşar ve kareyi
   kameradan KENDİ ÇEKER (pull). İtme (push) kipinde olsaydı, yazma yavaş
   olduğunda güdüm tikini bekletirdi. Aynı ders uçuş kaydında da alınmıştı.

⛔ HAM KARE YAZILIR — kutu çizilmez. Sebebi: kayıt, dedektörün ne gördüğünü
   değil KAMERANIN ne gördüğünü belgelemeli. Çizilen kutu bizim yorumumuz;
   hakem ham görüntüye bakmalı. (Analog FPV OSD'si zaten karenin içinde.)

⛔ DİSK DOLARSA UÇUŞ DURMAZ: yazma hatası sayılır, kayıt kapanır, güdüm
   sürer. Uçuşu bir kayıt hatası öldüremez.
================================================================================
"""
import os
import threading
import time


class VideoCfg:
    #: Saniyede kaç kare yazılır. Yakalama ~15 Hz; üstüne çıkmak boşuna.
    FPS = float(os.environ.get("DOW_VIDEO_FPS", 12.0))
    #: Dört harfli codec. mp4v her yerde çalışır; H264 daha küçük ama
    #  OpenCV derlemesine bağlı.
    CODEC = os.environ.get("DOW_VIDEO_CODEC", "mp4v")
    #: Kayıt dizini.
    DIZIN = os.environ.get("DOW_VIDEO_DIZIN", "logs")


class VideoKaydi:
    """FPV karelerini dosyaya yazar. `basla()` / `dur()` ile denetlenir."""

    def __init__(self, kamera, cfg=VideoCfg):
        self.kam = kamera
        self.cfg = cfg
        self.aktif = False
        self.yol = ""
        self.hata = ""
        self.kare = 0
        self.atlanan = 0
        self._t0 = 0.0
        self._yazici = None
        self._is = None
        self._dur = threading.Event()
        self._kilit = threading.Lock()

    # ---------------- denetim ----------------
    def basla(self, ad_oneki="ucus"):
        """Kaydı başlat. Döner: (basarili, mesaj)."""
        with self._kilit:
            if self.aktif:
                return True, "kayıt zaten sürüyor"
            if self.kam is None:
                self.hata = "kamera yok"
                return False, self.hata
            kare, _, _ = self.kam.son_kare()
            if kare is None:
                self.hata = "kamera kare vermiyor — kayıt başlatılamaz"
                return False, self.hata
            try:
                import cv2
            except ImportError:
                self.hata = "opencv yok"
                return False, self.hata
            h, g = kare.shape[0], kare.shape[1]
            os.makedirs(self.cfg.DIZIN, exist_ok=True)
            self.yol = os.path.join(
                self.cfg.DIZIN,
                "%s_%s.mp4" % (ad_oneki, time.strftime("%Y%m%d_%H%M%S")))
            dortlu = cv2.VideoWriter_fourcc(*self.cfg.CODEC)
            self._yazici = cv2.VideoWriter(self.yol, dortlu,
                                           self.cfg.FPS, (g, h))
            if not self._yazici.isOpened():
                self.hata = "video dosyası açılamadı (codec %s)" % self.cfg.CODEC
                self._yazici = None
                return False, self.hata
            self.kare = 0
            self.atlanan = 0
            self.hata = ""
            self._t0 = time.monotonic()
            self._dur.clear()
            self.aktif = True
            self._is = threading.Thread(target=self._dongu, daemon=True,
                                        name="video-kayit")
            self._is.start()
            return True, self.yol

    def dur(self):
        with self._kilit:
            if not self.aktif:
                return
            self.aktif = False
        self._dur.set()
        if self._is:
            self._is.join(timeout=3.0)
        if self._yazici is not None:
            try:
                self._yazici.release()
            except Exception:
                pass
            self._yazici = None

    # ---------------- döngü ----------------
    def _dongu(self):
        periyot = 1.0 / max(1.0, self.cfg.FPS)
        son_sayac = -1
        while not self._dur.is_set():
            t0 = time.monotonic()
            try:
                kare, _, sayac = self.kam.son_kare()
                if kare is None:
                    self.atlanan += 1
                elif sayac == son_sayac:
                    # ⛔ AYNI KAREYİ TEKRAR YAZMA: kamera bizden yavaşsa
                    #   aynı görüntü defalarca yazılır ve video "donuk"
                    #   görünür. Sayaç değişmediyse atla.
                    self.atlanan += 1
                else:
                    son_sayac = sayac
                    self._yazici.write(kare)
                    self.kare += 1
            except Exception as e:
                # ⛔ KAYIT HATASI UÇUŞU DURDURMAZ.
                self.hata = "%s: %s" % (type(e).__name__, e)
                self.aktif = False
                break
            uyku = periyot - (time.monotonic() - t0)
            if uyku > 0:
                self._dur.wait(uyku)

    # ---------------- gösterim ----------------
    def durum(self):
        sure = (time.monotonic() - self._t0) if self.aktif else 0.0
        mb = 0.0
        if self.yol and os.path.exists(self.yol):
            try:
                mb = round(os.path.getsize(self.yol) / 1048576.0, 2)
            except OSError:
                pass
        return {"aktif": self.aktif, "yol": os.path.basename(self.yol),
                "kare": self.kare, "atlanan": self.atlanan,
                "sure_s": round(sure, 1), "mb": mb, "hata": self.hata,
                "fps": self.cfg.FPS}
