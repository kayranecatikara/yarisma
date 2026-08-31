# -*- coding: utf-8 -*-
"""
================================================================================
RTL — EVE DÖN (Return To Launch)
================================================================================
Aracı, GPS kullanarak KÖKEN noktasına (kalkış yerine) geri getirir.

⛔⛔ NİYE BETAFLIGHT'IN "GPS RESCUE"'SUNU KULLANMIYORUZ
   Yarışma şartnamesi YALNIZ ANGLE MOD'a izin veriyor. GPS Rescue ayrı
   bir uçuş kipidir; ona geçmek şartnameyi çiğnemek olurdu. Bu yüzden
   RTL'i KENDİMİZ, Angle modda, çubuk komutu üreterek yapıyoruz —
   otonom güdümle tamamen aynı yoldan.

MİMARİ — hakeme DOKUNULMAZ
   RTL, güdümün YERİNE geçen bir otonom kaynaktır. `komut.py`'deki DÖRT
   ŞART (panel OTONOM · pilot izni · taze setpoint · kumanda bağı)
   aynen geçerlidir; RTL de o kapıdan geçer. Yani:
     · pilot izni yoksa RTL de çalışmaz
     · kumanda kopuksa RTL de kesilir
     · panelde MANUEL'e basmak ya da kumandada çubuk oynatmak RTL'i keser
   Bu bilinçlidir: RTL bir KOLAYLIKtır, pilotun yerine geçmez.

DAVRANIŞ — üç aşama
   1. TIRMAN   : irtifa `IRTIFA_M`in altındaysa önce yüksel (engel payı).
                 Yatay hareket YOK — önce yükselip sonra dönmek, ağaç/bina
                 çarpma riskini azaltır.
   2. DÖN      : köken yönüne yatay uç. Mesafe azaldıkça hız lineer düşer
                 (`FREN_M` içinde), yoksa hedefi aşıp salınır.
   3. BEKLE    : `VARIS_M` yarıçapına girince yatay hız sıfırlanır ve
                 irtifa korunur — araç kökenin üstünde ASILI kalır.

⛔ KENDİLİĞİNDEN İNMİYOR. İniş kararı PİLOTUNDUR. Otomatik iniş, altında
  ne olduğunu bilmeyen bir aracı yere indirmek demektir; kazanç küçük,
  risk büyüktür. Pilot MANUEL'e alıp indirir.

⚠ KÖKEN ŞART. `KÖKEN KUR`'a basılmamışsa yerel çerçeve yoktur ve RTL
  nereye döneceğini BİLEMEZ. O durumda başlamayı REDDEDER.
================================================================================
"""
import math
import os


def _f(ad, varsayilan):
    v = os.environ.get(ad)
    if v is None or v.strip() == "":
        return float(varsayilan)
    return float(v)


class RtlCfg:
    #: Dönüş irtifası (m, kökene göre). Altındaysa ÖNCE tırmanır.
    #  30 m: ağaç/direk payı. Uçuş alanında daha yüksek engel varsa artır.
    IRTIFA_M = _f("DOW_RTL_IRTIFA", 30.0)
    #: Yatay yaklaşma hızı tavanı (m/s).
    HIZ_MS = _f("DOW_RTL_HIZ", 8.0)
    #: Bu mesafeden itibaren hız lineer azalır (m). Frensiz yaklaşma
    #  hedefi aşar ve araç kökenin etrafında salınır.
    FREN_M = _f("DOW_RTL_FREN", 25.0)
    #: Bu yarıçapa girince "vardı" sayılır ve yatay hız kesilir (m).
    VARIS_M = _f("DOW_RTL_VARIS", 5.0)
    #: Tırmanma/alçalma hızı tavanı (m/s).
    DIKEY_HIZ = _f("DOW_RTL_DIKEY_HIZ", 3.0)
    #: Bu irtifa farkının altında "irtifa tamam" sayılır (m).
    IRTIFA_TOL = _f("DOW_RTL_IRTIFA_TOL", 3.0)
    #: Burnu dönüş yönüne çevirme kazancı (°/s per °). 0 = yaw'a dokunma.
    K_YAW = _f("DOW_RTL_K_YAW", 1.5)
    #: Bu mesafenin altında burun çevrilmez (yakında yaw anlamsız, salınır).
    YAW_MIN_M = _f("DOW_RTL_YAW_MIN", 10.0)


class Rtl:
    """Eve dön denetleyicisi. Güdümle AYNI araç modelini (çevirici) kullanır.

    ⛔ Kendi araç modelini kurmaz: çubuk eşlemesi tek yerden gelmeli,
       yoksa RTL ile otonom güdüm farklı 'aynı komut' üretir.
    """

    def __init__(self, cevirici, cfg=RtlCfg):
        self.cev = cevirici
        self.cfg = cfg
        self.aktif = False
        self.asama = "-"          # TIRMAN | DON | BEKLE
        self.mesafe = None
        self.n_tik = 0
        self.sebep = ""

    # ---------------------------------------------------------------- açma
    def basla(self, cerceve_hazir):
        """RTL'i başlat. Köken yoksa REDDEDER."""
        if not cerceve_hazir:
            self.sebep = "köken kurulmadı — RTL nereye döneceğini bilemez"
            return False
        self.aktif = True
        self.asama = "TIRMAN"
        self.n_tik = 0
        self.sebep = ""
        return True

    def dur(self):
        self.aktif = False
        self.asama = "-"

    # ---------------------------------------------------------------- adım
    def adim(self, konum, v_olculen, yaw_rad, dt, olcum_yasi=0.0):
        """Bir tik. Döner: (throttle, pitch, roll, yaw_hedef_deg).

        `konum`      : (kuzey, doğu, yukarı) metre — KÖKENE göre
        `v_olculen`  : (vx, vy, vz) ölçülen hız
        `yaw_rad`    : aracın yönelimi
        """
        c = self.cfg
        self.n_tik += 1
        kx, ky, kz = konum
        # ⭐ HEDEF: KÖKEN = (0, 0). Yerel çerçevenin tanımı gereği.
        mesafe = math.hypot(kx, ky)
        self.mesafe = mesafe

        # ---- dikey: önce güvenli irtifaya çık ----
        irtifa_hatasi = c.IRTIFA_M - kz
        if irtifa_hatasi > c.IRTIFA_TOL:
            vz_hedef = min(c.DIKEY_HIZ, irtifa_hatasi * 0.5)
            tirmaniyor = True
        elif irtifa_hatasi < -c.IRTIFA_TOL:
            # ⚠ ALÇALMA SINIRLI: RTL indirmez, yalnız fazla irtifayı bırakır.
            vz_hedef = max(-c.DIKEY_HIZ * 0.5, irtifa_hatasi * 0.3)
            tirmaniyor = False
        else:
            vz_hedef = 0.0
            tirmaniyor = False

        # ---- yatay: tırmanırken YATAY HAREKET YOK ----
        if tirmaniyor:
            self.asama = "TIRMAN"
            vx_hedef = vy_hedef = 0.0
        elif mesafe <= c.VARIS_M:
            self.asama = "BEKLE"
            vx_hedef = vy_hedef = 0.0
        else:
            self.asama = "DON"
            # ⛔ FREN: mesafe azaldıkça hız lineer düşer. Frensiz yaklaşma
            #   hedefi aşar ve araç kökenin etrafında salınır.
            hiz = c.HIZ_MS * min(1.0, mesafe / max(1e-6, c.FREN_M))
            # köken (0,0) yönü = konumun TERSİ
            vx_hedef = -kx / mesafe * hiz
            vy_hedef = -ky / mesafe * hiz

        # ---- yaw: burnu gidiş yönüne çevir ----
        yaw_hedef_deg = math.degrees(yaw_rad)
        if c.K_YAW > 0 and mesafe > c.YAW_MIN_M and not tirmaniyor:
            # kökene doğru kerteriz (kuzey=0°, saat yönü)
            istenen = math.degrees(math.atan2(-ky, -kx))
            hata = (istenen - math.degrees(yaw_rad) + 180.0) % 360.0 - 180.0
            yaw_hedef_deg = math.degrees(yaw_rad) + c.K_YAW * hata

        thr, pit, rol, yaw = self.cev.cevir(
            (vx_hedef, vy_hedef, -vz_hedef),      # NED: aşağı pozitif
            v_olculen, yaw_rad, yaw_hedef_deg - math.degrees(yaw_rad),
            dt=dt, olcum_yasi=olcum_yasi)
        return thr, pit, rol, yaw

    # ---------------------------------------------------------------- durum
    def durum(self):
        return {"aktif": self.aktif, "asama": self.asama,
                "mesafe": (round(self.mesafe, 1)
                           if self.mesafe is not None else None),
                "irtifa_hedef": self.cfg.IRTIFA_M,
                "tik": self.n_tik, "sebep": self.sebep}
