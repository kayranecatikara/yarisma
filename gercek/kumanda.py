# -*- coding: utf-8 -*-
"""
================================================================================
KUMANDA OKUYUCU — RadioMaster (EdgeTX) USB Joystick kipinde
================================================================================
EdgeTX, kumandayı bilgisayara standart bir oyun kolu (HID) gibi tanıtabilir
(SYS -> Hardware -> USB Mode: Joystick). Kullanıcı bu kipi DoW simülatöründe
zaten kullandı, yani yol KANITLI.

⛔ EKSEN SIRASI VARSAYILMAZ — ÖLÇÜLÜR.
   Hangi HID ekseninin hangi kanala denk geldiği; EdgeTX sürümüne, USB
   kipine (Joystick / Gamepad / MultiAxis) ve modelin kanal sırasına göre
   DEĞİŞİR. Yanlış eşleme "throttle verdim, araç yattı" demektir.
   `reel/araclar/kumanda_kalib.py` her ekseni tek tek oynatıp gerçek
   eşlemeyi bulur ve buraya yazılacak haritayı üretir.

⚠ BU DOSYA GÜDÜM DEĞİLDİR. Yalnız pilotun çubuklarını okur. Hakemlik
  (manuel mi otonom mu) `komut.py`'nin işidir.

--------------------------------------------------------------------------------
⛔⛔ İKİ OKUMA YOLU — VE NİYE BİRİNCİSİ VARSAYILAN
--------------------------------------------------------------------------------
  1) LINUX JOYSTICK API  (/dev/input/js*)   ← VARSAYILAN
  2) pygame/SDL                              ← yedek (Linux dışı, ya da js yok)

⛔ SDL YOLU BİR ARIZA KAYNAĞIDIR VE SAHADA GÖRÜLDÜ (2026-08-29):
   "kumandadan kontrol çalışıyor, sonra bir süre sonra donuyor."
   Sebep: `pygame.event.pump()` KOMUT İŞ PARÇACIĞINDAN çağrılıyor. SDL,
   olay kuyruğunun video alt sistemini kuran iş parçacığından pompalanmasını
   bekler; başka bir iş parçacığından pompalamak DESTEKLENMEZ ve sessizce
   takılabilir. Takılınca komut döngüsü de durur — çubuklar donar.

⭐ LINUX JOYSTICK API bu riski TAMAMEN kaldırır:
   * saf dosya okuması, olay pompası YOK, kütüphane YOK
   * bloke etmez (O_NONBLOCK), iş parçacığı güvenlidir
   * çekirdek arayüzü; kararlı ve on yıllardır aynı
   Biçim (8 bayt, küçük-sonlu):  <I zaman  h değer  B tip  B numara
     tip 0x02 = eksen · 0x01 = düğme · 0x80 = "ilk durum" biti
     eksen değeri: -32767 … +32767
================================================================================
"""
import glob
import os
import struct
import time


class KumandaCfg:
    #: HID ekseni -> mantıksal eksen. VARSAYILAN TAHMİNDİR, ölçülecek.
    #: EdgeTX Joystick kipinde kanallar genelde eksen 0..7'ye sırayla düşer;
    #: kanal sırası AETR ise: 0=roll 1=pitch 2=throttle 3=yaw 4..7=AUX
    EKSEN_ROLL     = int(os.environ.get("DOW_KMD_EKS_ROLL", 0))
    EKSEN_PITCH    = int(os.environ.get("DOW_KMD_EKS_PITCH", 1))
    EKSEN_THROTTLE = int(os.environ.get("DOW_KMD_EKS_THR", 2))
    EKSEN_YAW      = int(os.environ.get("DOW_KMD_EKS_YAW", 3))
    EKSEN_ARM      = int(os.environ.get("DOW_KMD_EKS_ARM", 4))      # AUX1/SA
    #: OTONOM İZİN anahtarı. ⛔ -1 = ANAHTAR YOK.
    #:   Kumandada boş bir anahtar yoksa bu eksen sabit -1.00 okunur ve
    #:   veto DAİMA kapalı kalır — otonom hiç açılamaz, sebebi de görünmez.
    #:   -1 verilince kumanda "izin konusunda fikrim yok" der (None) ve
    #:   izin PANELDEN gelir. Bekçi R67.
    EKSEN_KIP      = int(os.environ.get("DOW_KMD_EKS_KIP", 5))      # AUX2/SB
    #: İşaret düzeltmeleri (HID ekseni ters gelebilir) — ÖLÇÜLECEK
    TERS_ROLL     = os.environ.get("DOW_KMD_TERS_ROLL", "0") == "1"
    TERS_PITCH    = os.environ.get("DOW_KMD_TERS_PITCH", "0") == "1"
    TERS_THROTTLE = os.environ.get("DOW_KMD_TERS_THR", "0") == "1"
    TERS_YAW      = os.environ.get("DOW_KMD_TERS_YAW", "0") == "1"
    #: Anahtar eşiği: bu değerin üstü "açık" sayılır ([-1,+1] ölçeğinde)
    ANAHTAR_ESIK  = float(os.environ.get("DOW_KMD_ANAHTAR_ESIK", 0.5))
    #: Orta ölü bant — çubuk tam ortada durmuyorsa titremesin
    OLU_BANT      = float(os.environ.get("DOW_KMD_OLU_BANT", 0.02))


class Cubuklar:
    """Tek bir okumanın sonucu."""

    __slots__ = ("throttle", "pitch", "roll", "yaw", "arm", "kip_anahtari",
                 "t", "ham")

    def __init__(self, throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0,
                 arm=False, kip_anahtari=False, t=0.0, ham=None):
        self.throttle = throttle; self.pitch = pitch
        self.roll = roll; self.yaw = yaw
        self.arm = arm; self.kip_anahtari = kip_anahtari
        self.t = t; self.ham = ham or []

    def __repr__(self):
        return ("Cubuklar(thr=%+.3f pitch=%+.3f roll=%+.3f yaw=%+.3f "
                "arm=%s kip=%s)" % (self.throttle, self.pitch, self.roll,
                                    self.yaw, self.arm, self.kip_anahtari))


class _JsOkuyucu:
    """Linux joystick API (/dev/input/jsN) — bloke etmeyen, iş parçacığı güvenli.

    ⛔ NİYE AYRI SINIF: SDL'e hiç dokunmadan çalışır. `oku()` yalnız
       birikmiş olayları tüketir ve son eksen durumunu döndürür; hiçbir
       koşulda beklemez.
    """

    OLAY = struct.Struct("<IhBB")          # zaman, değer, tip, numara
    EKSEN, DUGME, ILK = 0x02, 0x01, 0x80

    def __init__(self, yol):
        self.yol = yol
        self.fd = None
        self.eksenler = []
        self.ad = ""

    def ac(self):
        try:
            self.fd = os.open(self.yol, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return False
        self.ad = self._ad()
        self.eksenler = []
        self.n_gercek = 0                   # çekirdeğin bildirdiği eksen sayısı
        # ⛔ AÇILIŞTA ÇEKİRDEK "ilk durum" OLAYLARINI GÖNDERİR (0x80 biti).
        #   Onları okumadan ilk `oku()` hepsini sıfır görür ve sonra
        #   toptan "hareket" sanırdı. Burada peşinen tüketilir.
        for _ in range(200):
            if not self._bir_olay():
                break
        return True

    def _ad(self):
        try:
            import fcntl
            tampon = bytearray(128)
            # JSIOCGNAME(len) = _IOC(READ, 'j', 0x13, len)
            fcntl.ioctl(self.fd, 0x80006A13 + (len(tampon) << 16), tampon)
            return tampon.split(b"\x00")[0].decode("utf-8", "replace")
        except Exception:
            return os.path.basename(self.yol)

    def _bir_olay(self):
        try:
            ham = os.read(self.fd, self.OLAY.size)
        except BlockingIOError:
            return False
        except OSError:
            self.kapat()
            return False
        if len(ham) < self.OLAY.size:
            return False
        _t, deger, tip, no = self.OLAY.unpack(ham)
        if (tip & ~self.ILK) == self.EKSEN:
            while no >= len(self.eksenler):
                self.eksenler.append(0.0)
            self.eksenler[no] = max(-1.0, min(1.0, deger / 32767.0))
            self.n_gercek = max(self.n_gercek, no + 1)
        return True

    def oku(self):
        """Birikmiş olayları tüket, eksen listesini döndür. Kopmuşsa None."""
        if self.fd is None:
            return None
        for _ in range(512):                # tek çağrıda sonsuza kadar okuma
            if not self._bir_olay():
                break
        return None if self.fd is None else list(self.eksenler)

    def kapat(self):
        try:
            if self.fd is not None:
                os.close(self.fd)
        except OSError:
            pass
        self.fd = None


class Kumanda:
    """EdgeTX kumandasını oyun kolu olarak okur (Linux js API, yedek: SDL).

    ⛔ AÇILIŞTA BAĞLANMAK ZORUNDA DEĞİL. Kumanda takılı değilse `hazir`
       False kalır ve `oku()` None döner. Çağıran buna göre davranır —
       çünkü "kumanda yok" bir hata değil, bir DURUMDUR (ör. tezgâhta
       yalnız otonom sınama).
    """

    def __init__(self, cfg=KumandaCfg, indeks=0):
        self.cfg = cfg
        self.indeks = indeks
        self.hazir = False
        self.ad = ""
        self._js = None
        self._pg = None
        self._jsapi = None          # Linux joystick API okuyucusu
        self.yol = "sdl"
        self.n_eksen = 0
        self.son = None
        self.hata = None

    def ac(self):
        """Önce Linux js API, olmazsa SDL. Tekrar çağrılabilir (sıcak takma)."""
        self.kapat()
        for y in sorted(glob.glob("/dev/input/js*")):
            o = _JsOkuyucu(y)
            if o.ac():
                self._jsapi = o
                self.ad = o.ad or y
                self.yol = y
                # ⛔ GERÇEK sayı, ayrılan tampon değil: panelde "16 eksen"
                #   yazması yanıltıcıydı (kumanda 7 bildiriyor).
                self.n_eksen = o.n_gercek or len(o.eksenler)
                self.hazir = True
                return True
        return self._sdl_ac()

    def _sdl_ac(self):
        """⭐ TEKRAR ÇAĞRILABİLİR: cihaz sonradan takılırsa yakalar.

        ⛔ `pygame.joystick.quit()` + `init()` ŞART: pygame cihaz listesini
           ÖNBELLEKLER. Sadece `get_count()` çağırmak, program açılışında
           takılı OLMAYAN bir kumandayı sonradan takınca ASLA görmez.
           Sahada tam bu yaşandı (2026-08-29): panel "takılı değil" diyordu.
        """
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            import pygame
            self._pg = pygame
            if not pygame.get_init():
                pygame.init()
            # cihaz listesini TAZELE
            try:
                pygame.joystick.quit()
            except Exception:
                pass
            pygame.joystick.init()
            if pygame.joystick.get_count() <= self.indeks:
                self.hata = ("oyun kolu bulunamadı (bulunan: %d). Kumanda "
                             "açık mı ve USB kipi 'Joystick' mi?"
                             % pygame.joystick.get_count())
                return False
            self._js = pygame.joystick.Joystick(self.indeks)
            self._js.init()
            self.ad = self._js.get_name()
            self.n_eksen = self._js.get_numaxes()
            self.hazir = True
            return True
        except Exception as e:
            self.hata = "%s: %s" % (type(e).__name__, e)
            return False

    def kapat(self):
        if self._jsapi is not None:
            self._jsapi.kapat()
            self._jsapi = None
        try:
            if self._js is not None:
                self._js.quit()
            if self._pg is not None:
                self._pg.joystick.quit()
        except Exception:
            pass
        self._js = self._pg = None
        self.hazir = False

    # ------------------------------------------------------------------
    def _eksen(self, ham, no, ters=False):
        if no < 0 or no >= len(ham):
            return 0.0
        v = float(ham[no])
        if ters:
            v = -v
        if abs(v) < self.cfg.OLU_BANT:
            return 0.0
        return -1.0 if v < -1.0 else (1.0 if v > 1.0 else v)

    def oku(self):
        """Bir okuma. Kumanda yoksa None.

        ⛔ Linux yolunda SDL'e HİÇ dokunulmaz — olay pompası yok, dolayısıyla
           iş parçacığı takılması da yok (bkz. modül başlığı).
        """
        if not self.hazir:
            return None
        if self._jsapi is not None:
            ham = self._jsapi.oku()
            if ham is None:
                self.hata = "joystick koptu: %s" % self.yol
                self.hazir = False
                return None
            self.n_eksen = len(ham)
        else:
            try:
                self._pg.event.pump()
                ham = [self._js.get_axis(i) for i in range(self.n_eksen)]
            except Exception as e:
                self.hata = "okuma: %s" % e
                self.hazir = False
                return None
        c = self.cfg
        s = Cubuklar(
            throttle=self._eksen(ham, c.EKSEN_THROTTLE, c.TERS_THROTTLE),
            pitch=self._eksen(ham, c.EKSEN_PITCH, c.TERS_PITCH),
            roll=self._eksen(ham, c.EKSEN_ROLL, c.TERS_ROLL),
            yaw=self._eksen(ham, c.EKSEN_YAW, c.TERS_YAW),
            arm=self._eksen(ham, c.EKSEN_ARM) >= c.ANAHTAR_ESIK,
            kip_anahtari=(None if c.EKSEN_KIP < 0
                          else self._eksen(ham, c.EKSEN_KIP) >= c.ANAHTAR_ESIK),
            t=time.monotonic(), ham=ham)
        self.son = s
        return s
