# -*- coding: utf-8 -*-
"""
================================================================================
CRSF (CROSSFIRE) PROTOKOLÜ — komut YUKARI, telemetri AŞAĞI
================================================================================
Gerçek drone ile tek konuşma dilimiz budur. Yer bilgisayarı bir seri porttan
CRSF çerçeveleri yazar (kumanda kanalları), aynı porttan CRSF çerçeveleri
okur (telemetri). Fiziksel yol:

    [YER PC] --USB seri--> [ELRS TX modülü] ))) 2.4 GHz ((( [ELRS RX] --UART--> [F405]
             <--------------------- telemetri geri --------------------------

⚠ BU DOSYA YALNIZ BAYTLARI BİLİR. Seri portu açmak, zamanlama, emniyet —
  hepsi ayrı dosyalarda. Böylece protokol, donanım olmadan masada tam
  olarak sınanabilir (bekçi R12-R20).

--------------------------------------------------------------------------------
1 · ÇERÇEVE BİÇİMİ
--------------------------------------------------------------------------------
    +---------+--------+------+-----------------+------+
    | ADRES   | UZUNLUK| TİP  | YÜK (payload)   | CRC8 |
    | 1 bayt  | 1 bayt |1 bayt| 0..60 bayt      |1 bayt|
    +---------+--------+------+-----------------+------+

  UZUNLUK = kendisinden SONRAKİ bayt sayısı = 1(tip) + len(yük) + 1(crc)
            ⛔ Adres ve uzunluk baytının kendisi SAYILMAZ. En sık yapılan
               hata budur; bir fazla/eksik sayınca alıcı senkronu kaybeder.
  CRC8    = TİP + YÜK üzerinden. Adres ve uzunluk CRC'ye GİRMEZ.

TERİMLER (CLAUDE.md §0.2):
  * CRC (döngüsel artıklık denetimi): baytların üzerinden hesaplanan bir
    "parmak izi". Alıcı aynı hesabı yapar; tutmazsa paket bozulmuştur ve
    ATILIR. Telsiz linkinde gürültü kaçınılmaz olduğu için şarttır —
    bozuk bir paketi komut sanmak, rastgele bir çubuk komutu uygulamaktır.
  * POLİNOM: CRC hesabının kuralı. CRSF, "CRC-8/DVB-S2" kullanır,
    polinom 0xD5, başlangıç 0x00, ters çevirme YOK.
    BAĞIMSIZ DOĞRULAMA NOKTASI: bu standardın bilinen sınama değeri,
    "123456789" metninin CRC'sinin 0xBC olmasıdır (bekçi R12 bunu sınar).

--------------------------------------------------------------------------------
2 · KUMANDA KANALLARI (yukarı) — tip 0x16
--------------------------------------------------------------------------------
16 kanal, her biri 11 BİT, arka arkaya paketlenir = 22 bayt.
Bit sırası: kanal 0'ın en düşük biti, ilk baytın en düşük bitidir
(küçük-sonlu bit dizilimi).

  DEĞER ARALIĞI ve MİKROSANİYE KARŞILIĞI (endüstri standardı):
        CRSF 172  ->  988 µs   (alt uç)
        CRSF 992  -> 1500 µs   (ORTA)
        CRSF 1811 -> 2012 µs   (üst uç)
    Dönüşüm:  µs = (crsf − 992) · 5/8 + 1500

  KANAL SIRASI — ⚠ AETR VARSAYILIYOR, DOĞRULANACAK:
        kanal 1 = ROLL     (aileron)
        kanal 2 = PITCH    (elevator)
        kanal 3 = THROTTLE
        kanal 4 = YAW      (rudder)
        kanal 5+ = AUX (arm, uçuş kipi, ...)
    Betaflight'ın `rcmap` ayarı bunu DEĞİŞTİREBİLİR. Bu yüzden sıra burada
    SABİT YAZILMAZ; `KanalHaritasi` ile verilir ve gerçek kartta
    `araclar/kanal_testi.py` ile TEK TEK doğrulanır. Yanlış harita =
    "pitch verdim, araç yattı" demektir.

--------------------------------------------------------------------------------
3 · TELEMETRİ (aşağı) — ihtiyacımız olan üç çerçeve
--------------------------------------------------------------------------------
  0x02 GPS       : enlem, boylam, yer hızı, ROTA, irtifa, uydu sayısı
  0x1E ATTITUDE  : pitch, roll, yaw  (radyan × 10000)
  0x07 VARIO     : düşey hız (cm/s)
  0x14 LINK_STATS: link kalitesi — EMNİYET için (link ölüyor mu?)

  Hepsi BÜYÜK-SONLU (big-endian) tam sayıdır. ⚠ Kumanda kanalları
  KÜÇÜK-sonlu bit dizilimiyken telemetri BÜYÜK-sonlu bayt sırasıdır;
  ikisi aynı protokolde farklıdır ve karıştırmak çöp veri üretir.

  ⛔ `heading` ALANI ROTA'DIR, BURUN DEĞİL. GPS'ten türetilir, yani aracın
     GERÇEKTEN gittiği yönü söyler. Burun yönü ATTITUDE çerçevesindeki
     `yaw`tır. Rüzgârda ikisi ayrışır (bkz. `konum.yer_hizindan_vektor`).
================================================================================
"""
import struct

# ---------------- adresler ----------------
ADRES_YAYIN        = 0x00
ADRES_UCUS_KARTI   = 0xC8   # flight controller
ADRES_EL_KUMANDASI = 0xEA   # radio transmitter (telemetri bize BUNUNLA gelir)
ADRES_TX_MODULU    = 0xEE   # CRSF transmitter — komutu BUNA yazarız

# ---------------- çerçeve tipleri ----------------
TIP_GPS          = 0x02
TIP_VARIO        = 0x07
TIP_PIL          = 0x08
TIP_BARO_IRTIFA  = 0x09
TIP_LINK         = 0x14
TIP_RC_KANALLAR  = 0x16
TIP_DURUS        = 0x1E     # ATTITUDE
TIP_UCUS_KIPI    = 0x21

# ---------------- kanal değer uçları ----------------
CRSF_MIN, CRSF_ORTA, CRSF_MAX = 172, 992, 1811
US_MIN,  US_ORTA,  US_MAX     = 988, 1500, 2012

EN_BUYUK_CERCEVE = 64        # adres+uzunluk+62; okuma tamponu için üst sınır


# ======================================================================
#  CRC-8 / DVB-S2  (polinom 0xD5)
# ======================================================================
def _crc_tablosu():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0xD5) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        t.append(c)
    return tuple(t)


_CRC = _crc_tablosu()


def crc8(veri):
    """CRSF'in CRC-8/DVB-S2'si. Sınama: crc8(b"123456789") == 0xBC."""
    c = 0
    for b in veri:
        c = _CRC[c ^ b]
    return c


# ======================================================================
#  ÇERÇEVE KURMA
# ======================================================================
def cerceve(tip, yuk, adres=ADRES_TX_MODULU):
    """Tam bir CRSF çerçevesi (bytes) kur.

    UZUNLUK alanı = 1 (tip) + len(yuk) + 1 (crc). Adres ve uzunluğun
    kendisi sayılmaz — bkz. modül başlığı §1.
    """
    yuk = bytes(yuk)
    govde = bytes([tip]) + yuk
    return bytes([adres, len(govde) + 1]) + govde + bytes([crc8(govde)])


# ======================================================================
#  KUMANDA KANALLARI
# ======================================================================
def cubuk_crsf(x, ters=False):
    """Çubuk konumunu [-1, +1] CRSF ham değerine (172..1811) çevirir.

    ⚠ SİMETRİ: orta nokta 992'dir ve iki yarı EŞİT GENİŞLİKTE DEĞİLDİR
      (992−172 = 820, 1811−992 = 819). Bir bitlik bu fark standardın
      kendisinden gelir; her yarı kendi genişliğiyle ölçeklenir ki
      x=−1 tam 172, x=+1 tam 1811 versin.
    """
    x = -float(x) if ters else float(x)
    x = -1.0 if x < -1.0 else (1.0 if x > 1.0 else x)
    if x >= 0.0:
        ham = CRSF_ORTA + x * (CRSF_MAX - CRSF_ORTA)
    else:
        ham = CRSF_ORTA + x * (CRSF_ORTA - CRSF_MIN)
    return int(round(ham))


def crsf_cubuk(ham):
    """Ters çevrim: CRSF ham değeri -> [-1, +1]. (Teşhis ve test için.)"""
    ham = float(ham)
    if ham >= CRSF_ORTA:
        return (ham - CRSF_ORTA) / float(CRSF_MAX - CRSF_ORTA)
    return (ham - CRSF_ORTA) / float(CRSF_ORTA - CRSF_MIN)


def crsf_us(ham):
    """CRSF ham değeri -> mikrosaniye (kartın gördüğü darbe genişliği)."""
    return (float(ham) - CRSF_ORTA) * 5.0 / 8.0 + US_ORTA


def us_crsf(us):
    return int(round((float(us) - US_ORTA) * 8.0 / 5.0 + CRSF_ORTA))


def kanallari_paketle(kanallar):
    """16 kanalı (her biri 0..2047) 22 bayta paketle — küçük-sonlu bit dizisi."""
    if len(kanallar) != 16:
        raise ValueError("tam 16 kanal gerekli, verilen: %d" % len(kanallar))
    bit = 0
    n = 0
    cikti = bytearray()
    for k in kanallar:
        bit |= (int(k) & 0x7FF) << n
        n += 11
        while n >= 8:
            cikti.append(bit & 0xFF)
            bit >>= 8
            n -= 8
    return bytes(cikti)


def kanallari_coz(yuk):
    """22 baytı 16 kanala geri aç. (Test ve teşhis için.)"""
    if len(yuk) != 22:
        raise ValueError("22 bayt gerekli, verilen: %d" % len(yuk))
    bit = 0
    n = 0
    cikti = []
    i = 0
    while len(cikti) < 16:
        while n < 11:
            bit |= yuk[i] << n
            n += 8
            i += 1
        cikti.append(bit & 0x7FF)
        bit >>= 11
        n -= 11
    return cikti


class KanalHaritasi:
    """Hangi mantıksal eksen hangi CRSF kanalına gidiyor (1'den başlar).

    ⛔ VARSAYILAN AETR'DİR AMA VARSAYIM DEĞİL — DOĞRULANACAK.
       Betaflight'ta `rcmap` bunu değiştirebilir ve yanlış harita, pitch
       komutunun aracı YATIRMASI demektir. `araclar/kanal_testi.py` her
       ekseni tek tek oynatıp kartın hangi kanalda gördüğünü gösterir.

    `ters_*` bayrakları eksen YÖNÜNÜ çevirir. Bunlar da ÖLÇÜLECEK
    (`araclar/isaret_olc.py`); tahmin edilmeyecek.
    """

    def __init__(self, roll=1, pitch=2, throttle=3, yaw=4, arm=5,
                 ters_roll=False, ters_pitch=False,
                 ters_throttle=False, ters_yaw=False):
        self.roll = roll; self.pitch = pitch
        self.throttle = throttle; self.yaw = yaw; self.arm = arm
        self.ters_roll = ters_roll; self.ters_pitch = ters_pitch
        self.ters_throttle = ters_throttle; self.ters_yaw = ters_yaw
        kullanilan = [roll, pitch, throttle, yaw, arm]
        if len(set(kullanilan)) != len(kullanilan):
            raise ValueError(
                "aynı kanala iki eksen atanmış: %s — bu, bir eksenin "
                "sessizce kaybolması demektir" % kullanilan)
        for k in kullanilan:
            if not 1 <= k <= 16:
                raise ValueError("kanal numarası 1..16 olmalı: %d" % k)


def rc_paketi(throttle, pitch, roll, yaw, arm=False, harita=None,
              aux=None, adres=ADRES_TX_MODULU):
    """Dört ekseni + arm anahtarını tam bir CRSF RC çerçevesine çevirir.

    Kullanılmayan kanallar ORTAYA (992) kurulur — 0'a değil. Sıfır ham
    değer, karta "sinyal en altta" der; bir AUX anahtarı yanlışlıkla
    ters kipi seçebilir.
    """
    h = harita or KanalHaritasi()
    kanallar = [CRSF_ORTA] * 16
    kanallar[h.roll - 1]     = cubuk_crsf(roll,     h.ters_roll)
    kanallar[h.pitch - 1]    = cubuk_crsf(pitch,    h.ters_pitch)
    kanallar[h.throttle - 1] = cubuk_crsf(throttle, h.ters_throttle)
    kanallar[h.yaw - 1]      = cubuk_crsf(yaw,      h.ters_yaw)
    kanallar[h.arm - 1]      = CRSF_MAX if arm else CRSF_MIN
    for kanal_no, deger in (aux or {}).items():
        kanallar[int(kanal_no) - 1] = cubuk_crsf(deger)
    return cerceve(TIP_RC_KANALLAR, kanallari_paketle(kanallar), adres)


# ======================================================================
#  TELEMETRİ ÇÖZÜMÜ
# ======================================================================
def _coz_gps(y):
    """0x02 — enlem, boylam, yer hızı, ROTA, irtifa, uydu."""
    if len(y) < 15:
        return None
    enlem, boylam, hiz, rota, irtifa, uydu = struct.unpack(">iiHHHB", y[:15])
    return {"enlem": enlem / 1e7,
            "boylam": boylam / 1e7,
            # km/h*10 -> m/s :  (v/10) km/h = (v/10)/3.6 m/s = v/36
            "yer_hizi_ms": hiz / 36.0,
            "rota_deg": rota / 100.0,
            # ⚠ +1000 m ÖTELEME: irtifa işaretsiz saklanır, deniz
            #   seviyesinin ALTI da temsil edilebilsin diye 1000 eklenir.
            "irtifa_amsl_m": irtifa - 1000.0,
            "uydu": uydu}


def _coz_durus(y):
    """0x1E — radyan × 10000, işaretli, büyük-sonlu. SIRA: pitch, roll, yaw."""
    if len(y) < 6:
        return None
    pitch, roll, yaw = struct.unpack(">hhh", y[:6])
    return {"pitch_rad": pitch / 10000.0,
            "roll_rad": roll / 10000.0,
            "yaw_rad": yaw / 10000.0}


def _coz_vario(y):
    if len(y) < 2:
        return None
    return {"dusey_hiz_ms": struct.unpack(">h", y[:2])[0] / 100.0}


def _coz_link(y):
    """0x14 — EMNİYET için: link kalitesi ve sinyal gücü."""
    if len(y) < 10:
        return None
    (r1, r2, lq, snr, ant, kip, guc, d_rssi, d_lq, d_snr) = struct.unpack(
        ">BBBbBBBBBb", y[:10])
    return {"yukari_rssi_dbm": -r1, "yukari_lq": lq, "yukari_snr": snr,
            "asagi_rssi_dbm": -d_rssi, "asagi_lq": d_lq, "asagi_snr": d_snr,
            "rf_kipi": kip, "tx_guc_kodu": guc}


def _coz_pil(y):
    if len(y) < 8:
        return None
    v, a, k1, k2, k3, yuzde = struct.unpack(">HHBBBB", y[:8])
    return {"gerilim_v": v / 10.0, "akim_a": a / 10.0,
            "tuketim_mah": (k1 << 16) | (k2 << 8) | k3, "pil_yuzde": yuzde}


COZUCULER = {
    TIP_GPS:   ("gps", _coz_gps),
    TIP_DURUS: ("durus", _coz_durus),
    TIP_VARIO: ("vario", _coz_vario),
    TIP_LINK:  ("link", _coz_link),
    TIP_PIL:   ("pil", _coz_pil),
}


class Cozucu:
    """Seri porttan gelen bayt AKIŞINI çerçevelere ayırır.

    NİYE "AKIŞ": seri port bir mesaj sınırı bilmez; `read()` çağrısı bir
    çerçevenin ortasında bitebilir ya da iki buçuk çerçeve birden
    getirebilir. Bu sınıf ne gelirse tamponlar, tam çerçeveleri çıkarır.

    ⛔ SENKRON KAYBI: gürültüde bir bayt düşerse tampon kayar ve bundan
       sonraki her çerçeve bozuk görünür. Çözüm, CRC tutmayınca TEK BAYT
       ilerleyip yeniden denemektir (aşağıda). Tamponu tümden atmak,
       sağlam çerçeveleri de çöpe atardı.
    """

    def __init__(self, adresler=(ADRES_EL_KUMANDASI, ADRES_TX_MODULU,
                                 ADRES_UCUS_KARTI, ADRES_YAYIN)):
        self.tampon = bytearray()
        self.adresler = set(adresler)
        # teşhis sayaçları (§5.1 mekanizma sütunları)
        self.n_cerceve = 0
        self.n_crc_hata = 0
        self.n_atilan_bayt = 0

    #: Tampon bunu aşarsa senkron kurulamıyor demektir; en eski yarı atılır.
    #: ⛔ SINIRSIZ TAMPON = SESSİZ BELLEK SIZINTISI. Yanlış baud ya da ters
    #:   kablo takılıysa hiçbir çerçeve çözülmez ve tampon saatlerce büyür.
    TAMPON_TAVAN = 4096

    def besle(self, veri):
        """Yeni baytları ver, çözülmüş çerçeveleri al: [(tip, yuk), ...]

        ⛔ NİYE `pop(0)` KULLANILMIYOR: bytearray'de baştan silme O(n)'dir;
           gürültülü bir akışta bayt bayt atarken toplam maliyet O(n²) olur.
           400000 baud'da tek okumada 1000+ bayt gelebiliyor -> 50 Hz'lik
           kontrol döngüsünü kilitlerdi. Bunun yerine bir OKUMA İMLECİ (i)
           ilerletilir ve tampon sonda TEK KEZ kırpılır: O(n).
        """
        self.tampon.extend(veri)
        cikti = []
        tam = self.tampon
        n = len(tam)
        i = 0
        adresler = self.adresler
        while True:
            while i < n and tam[i] not in adresler:
                i += 1
                self.n_atilan_bayt += 1
            if n - i < 3:
                break
            uzunluk = tam[i + 1]
            if not 2 <= uzunluk <= 62:
                i += 1; self.n_atilan_bayt += 1
                continue
            toplam = uzunluk + 2
            if n - i < toplam:
                break                            # çerçeve henüz tamamlanmadı
            govde = bytes(tam[i + 2:i + toplam - 1])       # tip + yük
            if crc8(govde) != tam[i + toplam - 1]:
                # ⛔ TEK BAYT İLERLE, tamponu ATMA: adres baytı gerçek
                #   veride de geçebiliyor; yanlış hizalanmış bir "çerçeve"
                #   sonrasında gerçek çerçeve bir bayt ötede olabilir.
                self.n_crc_hata += 1
                i += 1; self.n_atilan_bayt += 1
                continue
            cikti.append((govde[0], govde[1:]))
            self.n_cerceve += 1
            i += toplam
        del tam[:i]
        if len(tam) > self.TAMPON_TAVAN:
            atilan = len(tam) - self.TAMPON_TAVAN // 2
            del tam[:atilan]
            self.n_atilan_bayt += atilan
        return cikti

    def coz(self, veri):
        """besle() + tanınan çerçeveleri ADI/DEĞERİ ile sözlüğe çevir."""
        sonuc = {}
        for tip, yuk in self.besle(veri):
            girdi = COZUCULER.get(tip)
            if not girdi:
                continue
            ad, fn = girdi
            d = fn(yuk)
            if d is not None:
                sonuc[ad] = d
        return sonuc
