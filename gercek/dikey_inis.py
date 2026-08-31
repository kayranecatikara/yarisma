# -*- coding: utf-8 -*-
"""
================================================================================
DİKEY İNİŞ — uçuş kartının KENDİ kipleriyle, olduğu yerde aşağı in
================================================================================
⛔ NİYE BÖYLE: kullanıcı isteği (2026-08-30) — *"bir tuşa basayım, drone
   görevini kessin, olduğu konumda dursun ve dimdik aşağıya insin, GPS
   verisiyle kendini dengelesin"* + *"angle modda yapmaya çalışmak çok
   riskli, araç sert inebilir"*.

   Kullanıcı haklı. Angle modunda gaz çubuğu bir HIZ değil İTKİ komutudur;
   onu alçalma hızına çevirmek için `dikey.py`'deki kapalı döngü gerekir ve
   O DÖNGÜ HİÇ UÇMADI (panelde ölçüldü: `aktif: false`, 3470 pasif çağrı).
   Hiç uçmamış bir döngüye inişi emanet etmek, sert iniş demektir.

   ⭐ ÇÖZÜM: işi uçuş kartına ver. Betaflight'ta iki kip ZATEN KURULU ve
   yalnız şartname gerekçesiyle kapalı tutuluyordu; yarışma komitesi
   iniş gösterimi için kip serbestisi verdi (kullanıcı, 2026-08-31).

       ALT HOLD  AUX2 (kanal 6)  1700-2100   barometreyle irtifa tutar
       POS HOLD  AUX4 (kanal 8)  1700-2100   GPS ile konumu tutar

--------------------------------------------------------------------------------
TERİMLER (CLAUDE.md §0.2)
--------------------------------------------------------------------------------
  * ALT HOLD (irtifa tutma): uçuş kartı barometreyle irtifayı sabit tutar.
    Gaz çubuğunun anlamı DEĞİŞİR: merkezde "irtifayı koru", merkezin
    altında "şu hızda alçal". Yani çubuk artık itki değil HIZ komutudur —
    bizim `dikey.py`'de yapmaya çalıştığımız şeyin kartın içindeki hâli.
  * POS HOLD (konum tutma): uçuş kartı GPS ile yatay konumu sabit tutar;
    rüzgâr sürüklerse kendi düzeltir. Yatay çubuklar merkezde bırakılır.
  * ÖLÜ BANT (deadband): çubuğun merkez civarında komut üretmeyen aralığı.
    ALT HOLD'da vardır; çubuğu az indirmek HİÇBİR ŞEY yapmayabilir.
    Bu yüzden iniş çubuğu değeri AYARLANABİLİR ve ilk uçuşta ÖLÇÜLMELİDİR.
  * EĞİM (ramp): komutun aniden değil, saniyeler içinde kademeli değişmesi.
    Gaz çubuğunu bir anda indirmek, kip yeni oturmuşken aracı sarsar.

--------------------------------------------------------------------------------
AŞAMALAR
--------------------------------------------------------------------------------
  TUT : ek kanallar açılır, gaz çubuğu MERKEZDE. Araç olduğu yerde asılı
        kalır. Bu bekleme kasıtlıdır: kiplerin gerçekten tuttuğunu
        operatör GÖRSÜN, sonra alçalma başlasın.
  IN  : gaz çubuğu, `RAMP_S` saniyede merkezden `INIS_CUBUK`'a iner ve
        orada kalır. Araç sabit hızla alçalır.

⛔ KENDİLİĞİNDEN DISARM ETMEZ. Havada disarm = serbest düşüş; bu deponun
   değişmez kuralı. Yere değince pilot disarm eder, ya da panelden
   "İNİŞ — TÜMÜNÜ KES" ile kartın kendi AUTO-LAND'ine bırakılır.

⛔ PİLOT ÇUBUĞA DOKUNURSA EK KANALLAR DÜŞER. Bu, hakemin içinde yapısal
   olarak sağlanıyor (`komut.py`: aux yalnız kaynak=="OTONOM" iken geçer).
   Sebebi: ALT HOLD açıkken gaz çubuğu hız komutudur; pilot devraldığında
   çubuğunun anlamının sessizce değişmiş olması kabul edilemez.
================================================================================
"""
import os
import time


def _f(ad, varsayilan):
    try:
        return float(os.environ.get(ad, varsayilan))
    except (TypeError, ValueError):
        return varsayilan


def _i(ad, varsayilan):
    try:
        return int(os.environ.get(ad, varsayilan))
    except (TypeError, ValueError):
        return varsayilan


class DikeyInisCfg:
    #: ALT HOLD kanalı (Betaflight'ta AUX2 = kanal 6, aralık 1700-2100).
    ALTHOLD_KANAL = _i("DOW_INIS_ALTHOLD_KANAL", 6)
    #: POS HOLD kanalı (AUX4 = kanal 8).
    POSHOLD_KANAL = _i("DOW_INIS_POSHOLD_KANAL", 8)
    #: Kipleri açan çubuk değeri. 0.78 -> ~1900 µs (eşik 1700'ün ÜSTÜ).
    #  `skydagger.cubuk_us`: 1500 + x*512  ->  0.78 = 1899 µs.
    AUX_CUBUK = _f("DOW_INIS_AUX_CUBUK", 0.78)
    #: Alçalmadan önce olduğu yerde asılı kalma süresi (s).
    TUT_S = _f("DOW_INIS_TUT_S", 3.0)
    #: Gaz çubuğunun merkezden iniş değerine inme süresi (s).
    RAMP_S = _f("DOW_INIS_RAMP_S", 3.0)
    #: İniş gaz çubuğu. Merkezin ALTINDA olmalı (negatif).
    #
    #  ⛔⛔ ÖLÜ BANT HESABI (Betaflight `diff all`, 2026-08-31):
    #    ALT HOLD'da gaz çubuğu merkez civarında ÖLÜ BANTTADIR ve hiçbir
    #    komut üretmez. `alt_hold_deadband` diff'te görünmüyor, yani
    #    VARSAYILANDA (%20). Çubuk→µs eşlemesi 1500 ± 512 olduğuna göre
    #    %20 = 102 µs = çubuk 0.20 demektir:
    #
    #        çubuk   µs    sapma        sonuç
    #        -0.20  1398  102 µs (%20)  ⛔ TAM SINIRDA — alçalmayabilir
    #        -0.25  1372  128 µs (%25)  ✔
    #        -0.35  1321  179 µs (%35)  ✔ seçilen — bandın dışında, yumuşak
    #        -0.50  1244  256 µs (%50)  ✔ ama hızlı
    #
    #    İLK DEĞERİM -0.20'YDİ ve TAM ÖLÜ BANDIN SINIRINDAYDI: araç büyük
    #    ihtimalle hiç alçalmayacaktı. -0.35'e çekildi.
    #
    #  ⚠ İLK UÇUŞTA ALÇALMA HIZI ÖLÇÜLECEK. Ölü bandın gerçek değeri
    #    CLI'de `get alt_hold_deadband` ile teyit edilir.
    INIS_CUBUK = _f("DOW_INIS_CUBUK", -0.35)
    #: ALT HOLD'un ölü bandı, çubuk biriminde. ARAÇTAN OKUNDU (2026-08-31):
    #  `get alt_hold_deadband` -> 20 (yüzde). Çubuk eşlemesi 1500±512
    #  olduğuna göre %20 = 0.20 çubuk.
    #
    #  ⛔ NİYE AYRI BİR ALAN: rampa SIFIRDAN başlarsa ilk %57'si bu bandın
    #    İÇİNDE geçer — araç 1.7 saniye hiçbir şey yapmaz, sonra alçalma
    #    BİRDEN başlar. Rampanın amacı tam da bunu önlemekti. Bandın
    #    KENARINDAN başlayınca alçalma hızı gerçekten 0'dan hedefe
    #    yumuşak çıkar.
    OLU_BANT = _f("DOW_INIS_OLU_BANT", 0.20)


class DikeyInis:
    """Dikey iniş durum makinesi. Çubuk ve ek kanal üretir; ARM'a DOKUNMAZ."""

    def __init__(self, cfg=DikeyInisCfg):
        self.cfg = cfg
        self.aktif = False
        self.asama = "-"
        self.sebep = ""
        self._t0 = 0.0
        self._thr = 0.0

    # ---------------- denetim ----------------
    def basla(self):
        """İnişi başlat. Döner: başladı mı."""
        if self.aktif:
            return True
        self.aktif = True
        self.asama = "TUT"
        self.sebep = ""
        self._t0 = time.monotonic()
        self._thr = 0.0
        return True

    def dur(self):
        self.aktif = False
        self.asama = "-"
        self._thr = 0.0

    # ---------------- üretim ----------------
    def aux(self):
        """Ek kanallar. İniş kapalıyken BOŞ — çerçeve eskisiyle aynı kalır."""
        if not self.aktif:
            return {}
        c = self.cfg
        return {c.ALTHOLD_KANAL: c.AUX_CUBUK, c.POSHOLD_KANAL: c.AUX_CUBUK}

    def adim(self, periyot=None):
        """Bir tik. Döner: (throttle, pitch, roll, yaw).

        Yatay çubuklar DAİMA sıfır: POS HOLD'un tuttuğu konumu çubukla
        bozmayalım. Yaw da sıfır — burnu çevirmenin inişe faydası yok,
        zararı var (rüzgârda savrulur).
        """
        if not self.aktif:
            return 0.0, 0.0, 0.0, 0.0
        c = self.cfg
        gecen = time.monotonic() - self._t0
        if gecen < c.TUT_S:
            self.asama = "TUT"
            self._thr = 0.0
        else:
            self.asama = "IN"
            if c.RAMP_S > 0:
                oran = min(1.0, (gecen - c.TUT_S) / c.RAMP_S)
            else:
                oran = 1.0
            # ⛔ RAMPA ÖLÜ BANDIN KENARINDAN BAŞLAR, sıfırdan değil.
            #   Bandın içi zaten "alçalma yok" demek; oradan başlamak
            #   rampanın ilk yarısını boşa harcar ve alçalmayı ani yapar.
            bas = -abs(c.OLU_BANT)
            self._thr = bas + (c.INIS_CUBUK - bas) * oran
        return self._thr, 0.0, 0.0, 0.0

    # ---------------- gösterim ----------------
    def durum(self):
        c = self.cfg
        return {"aktif": self.aktif, "asama": self.asama,
                "gaz_cubugu": round(self._thr, 3),
                "hedef_cubuk": c.INIS_CUBUK,
                "olu_bant": c.OLU_BANT,
                "gecen_s": (round(time.monotonic() - self._t0, 1)
                            if self.aktif else 0.0),
                "kanallar": sorted(self.aux().keys()),
                "sebep": self.sebep}
