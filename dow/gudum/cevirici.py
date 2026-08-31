# -*- coding: utf-8 -*-
"""
================================================================================
HIZ → KUMANDA ÇUBUĞU ÇEVİRİCİSİ
================================================================================
Gazebo'da güdüm yasamız HIZ SETPOINT'i üretiyordu (vx, vy, vz, yaw_rate) ve
ArduPilot'un AC_PosControl katmanı bunu gövde yatış açısına çeviriyordu.
Drones of War'da o katman YOK — SDK yalnız kumanda çubuğu kabul ediyor.

BU DOSYA O EKSİK KATMANDIR. Güdüm yasasına DOKUNMAZ; yalnız çıktısını okur.
Bu, §5.10'un istediği "yapısal garanti": güdüm kodunda tek satır değişmeden
çevirici değiştirilebilir, tersi de doğru.

TERİMLER (CLAUDE.md §0.2 — hiçbir terim tanımsız bırakılmaz):
  * hız setpoint'i : "şu hızla git" komutu, m/s.
  * kumanda çubuğu : -1..+1 birimsiz. DoW'da bu bir HEDEF YATIŞ AÇISIDIR
                     (Angle Mode), dönüş hızı değil.
  * kararlı-hâl    : komut sabit tutulduğunda sistemin oturduğu değer.
  * zaman sabiti τ : basamak komuta tepkinin son değerinin %63'üne ulaşma
                     süresi. Araç yatış τ'su ölçüldü: 0.211 s (belge 0.20).
  * doyum (clamp)  : bir büyüklüğün tavana dayanıp artamaması.

ÖLÇÜLMÜŞ ZARF (kaynak: DOW_PARAMETRE_PAKETI + kendi doğrulamam):
  yatay hız tavanı ....... 34.6 m/s   (belge 120 km/h = 33.33)
  tırmanma tavanı ........ +33.98 m/s
  ALÇALMA tavanı ......... -5.65 m/s  ⚠ 6 KAT ASİMETRİK
  yatay ivme ............. 34-39 m/s² (60° yatışta beklenen 17.0'ın 2.3 katı)
  yatış zaman sabiti ..... 0.211 s
  ölü zaman .............. 46 ms
  yaw tavanı ............. 214 °/s
================================================================================
"""
import math
import os


def _f(ad, v):
    return float(os.environ.get(ad, v))


def _s(ad, v):
    return os.environ.get(ad, v).strip().lower()


class CevCfg:
    """Çevirici ayarları — yani ARACIN ÖLÇÜLMÜŞ MODELİ.

    ⭐⭐ BU SINIF BİR GÜDÜM AYARI DEĞİL, BİR ARAÇ TARİFİDİR (2026-08-29).
    Buradaki her sayı "hangi çubuk ne yapar" sorusunun O ARACA ait cevabıdır
    ve ÖLÇÜLEREK bulunur. Bu yüzden gerçek donanıma geçerken değişmesi
    GEREKEN yer burasıdır — güdüm yasalarının kendisi değil.
    (Bekçi B11 bu dosyanın güdüm yasasını İTHAL ETMEDİĞİNİ sınar; bu
     kural o kadar katıdır ki yasanın dosya adını YORUMDA anmak bile
     testi kırar. Kasten öyle: yapısal ayrım, ancak korunursa vardır.)

    Ayrım niye önemli (CLAUDE.md §0.2):
      GÜDÜM YASASI  "hedefe göre saniyede kaç metre gitmeliyim" der.
                    Bu, aracın ne olduğundan BAĞIMSIZ bir karardır.
      ARAÇ MODELİ   "saniyede şu kadar metre gitmek için çubuğu nereye
                    koymalıyım" der. Bu TAMAMEN araca bağlıdır.
    Simden gerçeğe taşırken ikincisi yeniden ölçülür, birincisi DOKUNULMAZ.

    Her alan `DOW_CEV_*` env değişkeniyle geçersiz kılınabilir; VARSAYILANLAR
    DoW'da ölçülen değerlerdir, yani env verilmezse davranış BİT BİT eskisi
    gibidir (bekçi R24 bunu sınar).
    """

    # --- [1] EKSEN ---
    # Gazebo NED: X kuzey, Y doğu, Z AŞAĞI (vz>0 = alçal).
    # Unreal:     X ileri, Y sağ,  Z YUKARI (throttle>0 = tırman).
    Z_ISARET = _f("DOW_CEV_Z_ISARET", -1.0)   # NED vz -> "yukarı" hızı
    # ⛔ YANAL EKSEN İŞARETİ — ÖLÇÜLDÜ, TAHMİN DEĞİL.
    #   Unreal SOL-ELLİ (X ileri, Y sağ, Z yukarı, yaw saat yönü); benim
    #   dunya_govde() dönüşümüm SAĞ-ELLİ varsayıyordu. Sonuç: yanal komut
    #   TERS yöne gidiyor, hata kapanacağına BÜYÜYOR, roll -1'e çakılıyor
    #   (ölçüldü: tiklerin %94'ünde doyum) ve araç hedefe gitmek yerine
    #   DAİRE çiziyor. Kapanma hızı medyan -3.78 m/s = uzaklaşıyor.
    #   ÖLÇÜM (200 m'de, 3 s saf komut, gerçek yer değişimi):
    #     pitch +0.6 -> gövde ileri +66.6 m, gövde sağ  -0.0  ✅ doğru
    #     roll  +0.6 -> gövde ileri  +6.6 m, gövde sağ -66.8  ❌ TERS
    #   ⭐ GERÇEK ARAÇTA BU DEĞER MUHTEMELEN +1.0'DIR (standart uçak
    #     sözleşmesi: +roll sağa yatırır, araç sağa gider). AMA "muhtemelen"
    #     UÇURULMAZ: `reel/araclar/isaret_olc.py` ölçer, sonuç buraya
    #     DOW_CEV_Y_ISARET ile verilir. Ölçülmeden otonom uçuş AÇILMAZ.
    Y_ISARET = _f("DOW_CEV_Y_ISARET", -1.0)   # DoW'da ölçüldü: +roll SOLA

    # --- [2] YATAY İÇ DÖNGÜ ---
    # a_istenen = K_V * (v_hedef - v_olculen)
    # K_V birimi 1/s; zaman sabiti tau = 1/K_V.
    # Yatış tau'su 0.211 s. İç döngü ondan YAVAŞ olmalı, yoksa iki döngü
    # birbirini kovalar ve salınır. K_V=1.5 -> tau=0.67 s = 3.2 kat yavaş.
    K_V = _f("DOW_CEV_KV", 1.5)

    # --- [3] İVME -> ÇUBUK ---
    # İki aday model (hangisinin doğru olduğu G2 ölçümüyle belirlenecek):
    #   "aci"   : stick = atan(a/g) / MAX_YATIS   (klasik multikopter fiziği)
    #   "dogru" : stick = a / A_MAX               (oyun doğrudan uyguluyorsa)
    # ⚠ Zarf ölçümü 60° yatışta 34-39 m/s² buldu; açı modeli 17.0 öngörür.
    #   Bu, "dogru" modelin daha olası olduğuna işaret eder — ama ÖLÇÜLECEK.
    #   ⭐ GERÇEK ARAÇ İÇİN DOĞRU OLAN "aci"DİR (2026-08-29).
    #     Angle modunda çubuk AÇIYA doğrusal eşlenir; yatay ivme ise
    #     a = g·tan(açı) ile açıya DOĞRUSAL DEĞİL bağlıdır. "dogru" modeli
    #     DoW için seçilmişti çünkü oyun fiziği gerçek dışıydı: 60° yatışta
    #     34 m/s² veriyordu, fizik 17.0 der (TAM İKİ KAT).
    #     Ölçülen kartta angle_limit = 60 -> gerçek tavan 17.0 m/s².
    #     Geçiş: DOW_CEV_MODEL=aci  DOW_CEV_ACI_MAX=60
    MODEL = _s("DOW_CEV_MODEL", "dogru")
    A_MAX = _f("DOW_CEV_A_MAX", 34.0)      # m/s²; "dogru" modelde tam çubuk
    MAX_YATIS_DEG = _f("DOW_CEV_ACI_MAX", 60.0)  # "aci" modelinde tam çubuk açısı

    # --- DİKEY: ÖLÇÜLMÜŞ MODEL (2026-08-21, kendi uçuşumuz, DoW V5.0.0) ---
    # throttle bir HIZ komutudur -> ivme kademesi YOK. Ama eşleme İKİ KOLLU ve
    # tam sıfırda SÜREKSİZ. Ölçüm (her nokta 5-6 s kararlı hâl, n=26):
    #
    #   thr  +1.00 +0.75 +0.50 +0.25 +0.10 +0.05 +0.01 | 0.00 | -0.001 -0.10 -0.60 -1.00
    #   vz   33.51 25.04 16.80  8.79  4.06  2.47  1.20 | 0.88 |  9.31   7.93 -0.24 -6.95
    #
    # ⛔⛔ LANDMINE: thr = -0.001 -> +9.31 m/s TIRMANMA. thr = 0.000 -> +0.88.
    #    Yani "eksi bir binde bir" irtifa tutma yerine 9 m/s tırmandırır.
    #    Bu, ana_kontrol.py'nin not ettiği "kacak tirmanma"nın KÖK NEDENİDİR.
    #    KURAL: 0 ile HOVER_THR arasına ASLA komut verilmez (aradaki bant zehirli).
    #
    # POZİTİF KOL : vz = 32.64*thr + 0.869      (thr > 0)
    # NEGATİF KOL : vz = 16.78*thr + 9.835      (thr <= HOVER_THR)
    # TAM SIFIR   : oyunun özel İRTİFA-TUTMA kipi (vz ~ +0.88, sürüklenme)
    POZ_EGIM   = _f("DOW_CEV_POZ_EGIM", 32.64)     # (m/s)/birim
    POZ_KESIM  = _f("DOW_CEV_POZ_KESIM", 0.869)     # m/s
    NEG_EGIM   = _f("DOW_CEV_NEG_EGIM", 16.78)     # (m/s)/birim
    NEG_KESIM  = _f("DOW_CEV_NEG_KESIM", 9.835)     # m/s
    HOVER_THR  = _f("DOW_CEV_HOVER_THR", -0.586)    # vz=0 veren throttle (negatif kolun sıfır geçişi)
    TUT_BANDI  = _f("DOW_CEV_TUT_BANDI", 0.05)      # |vz_istenen| bunun altındaysa thr=0 (irtifa-tut kipi)
    VZ_MAX_TIRMAN = _f("DOW_CEV_VZ_MAX_TIRMAN", 33.51)  # m/s; ÖLÇÜLDÜ (belge 120 km/h = 33.33 ile uyumlu)
    VZ_MAX_ALCAL  = _f("DOW_CEV_VZ_MAX_ALCAL", 6.95)   # m/s; ÖLÇÜLDÜ @thr=-1
    # ⚠ BELGE YANLIŞ: README "-1 = serbest düşüş" diyor; serbest düşüş 5 s'de
    #   -49 m/s verirdi, ÖLÇÜLEN -6.95. Belge bu maddede güvenilmez.
    # ⚠ ASİMETRİ 4.8 KAT: tırmanma 33.5, alçalma 6.95. Tek VZ_MAX kullanmak
    #   alçalma komutunu ~5 kat abartır.

    # --- YAW ---
    # Araç 214 °/s yapabiliyor AMA hızlı yaw görüntüyü bulandırıp dedektörü
    # kırar. Gazebo'daki 120 °/s sınırı KORUNUYOR (bilinçli tercih).
    YAW_RATE_MAX_DEG = _f("DOW_CEV_YAW_MAX", 120.0)

    # --- ÇUBUK EĞİM SINIRI ---
    # Komut/tik en çok bu kadar değişir. Araç yatışı zaten 0.211 s ile
    # yumuşuyor; bu sınır ONDAN GEVŞEK olmalı, yoksa iki sönümleme üst üste
    # binip tepkiyi geciktirir. 50 Hz'de 0.15 -> tam çubuk 0.13 s'de.
    MAX_DELTA = _f("DOW_CEV_MAX_DELTA", 0.15)


def _kirp(x, lo=-1.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _egim_sinirla(hedef, onceki, maks):
    return onceki + _kirp(hedef - onceki, -maks, maks)


class HizCubukCevirici:
    """Hız setpoint'ini kumanda çubuğuna çevirir.

    KULLANIM:
        cev = HizCubukCevirici()
        thr, pitch, roll, yaw = cev.cevir(
            v_hedef_ned=(vx, vy, vz),      # m/s, NED (güdümün ürettiği)
            v_olculen_unreal=(vx,vy,vz),   # m/s, Unreal (SDK'dan)
            yaw_rad=...,                   # aracın burun açısı
            yaw_rate_hedef_deg=...)        # °/s
    """

    def __init__(self, cfg=CevCfg, dikey=None):
        self.cfg = cfg
        self._onceki = {"thr": 0.0, "pitch": 0.0, "roll": 0.0, "yaw": 0.0}
        # ⭐ DİKEY DİKİŞİ (2026-08-29) — gerçek araç için.
        #   None  -> `_vz_cubuk()` kullanılır: DoW'da ÖLÇÜLMÜŞ statik eşleme.
        #            (throttle orada gerçekten bir HIZ komutuydu.)
        #   nesne -> `dikey.hesapla(...)` kullanılır: KAPALI DÖNGÜ.
        #            Gerçek araçta Angle modunda throttle bir İTKİ komutudur;
        #            statik eşleme TANIMSIZDIR. Ayrıntı: reel/gercek/dikey.py
        #   ⛔ None iken tek satır kod yolu değişmez (bekçi R34, denklik.py).
        self.dikey = dikey
        # teşhis: mekanizma kapısı (§5.1) için loglanır
        self.tani = {}

    def sifirla(self):
        self._onceki = {"thr": 0.0, "pitch": 0.0, "roll": 0.0, "yaw": 0.0}

    # ---------------- [1] eksen ----------------
    @staticmethod
    def dunya_govde(vx, vy, yaw_rad, y_isaret=None):
        """Dünya yatay hızını GÖVDE çerçevesine çevirir.
        ileri = burun yönü, sag = burnun sağı.
        y_isaret: Unreal'in sol-elli ekseni için ölçülmüş düzeltme (bkz. CevCfg)."""
        if y_isaret is None: y_isaret = CevCfg.Y_ISARET
        c, s = math.cos(yaw_rad), math.sin(yaw_rad)
        ileri = vx * c + vy * s
        sag   = y_isaret * (-vx * s + vy * c)
        return ileri, sag

    # ---------------- [3] ivme -> çubuk ----------------
    def _ivme_cubuk(self, a):
        """Tek eksende istenen ivmeyi çubuk konumuna çevirir."""
        c = self.cfg
        if c.MODEL == "aci":
            # Klasik: yatış açısı phi için yatay ivme a = g*tan(phi)
            aci = math.degrees(math.atan2(a, 9.81))
            return _kirp(aci / c.MAX_YATIS_DEG)
        # "dogru": oyun ivmeyi doğrudan uyguluyor
        return _kirp(a / c.A_MAX)

    def _vz_cubuk(self, vz):
        """İstenen dikey hızı (m/s, +yukarı) throttle'a çevirir — ÖLÇÜLMÜŞ model.
        Doğrulandı (istenen -> ölçülen): +10 -> +10.38 | -2 -> -1.88 |
        -5 -> -4.78 | -6.5 -> -6.26  (hata %4-6)."""
        c = self.cfg
        if abs(vz) < c.TUT_BANDI:
            # ⛔ BURADA 0.0 DÖNDÜRÜYORDUM — YANLIŞTI.
            # Oyunun "irtifa tut" kipi (thr=0) aslında +0.88 m/s TIRMANIYOR.
            # Koşular arasında öyle bırakınca drone 180 m'den 5821 m'ye çıktı
            # ve iki ölçüm koşusu boşa gitti. Doğru denge: HOVER_THR (-0.586),
            # orada ölçülen vz = -0.235 m/s (hafif alçalma = güvenli taraf).
            return c.HOVER_THR
        if vz > 0.0:
            return _kirp((vz - c.POZ_KESIM) / c.POZ_EGIM, 0.0, 1.0)
        # alçalma: negatif kol. ⛔ Sonuç ASLA (HOVER_THR, 0) zehirli bandına
        # düşmez — o bantta araç 9 m/s TIRMANIR.
        return _kirp((vz - c.NEG_KESIM) / c.NEG_EGIM, -1.0, c.HOVER_THR)

    # ---------------- ana ----------------
    def cevir(self, v_hedef_ned, v_olculen_unreal, yaw_rad,
              yaw_rate_hedef_deg=0.0, dt=None, olcum_yasi=0.0):
        """`dt` ve `olcum_yasi` YALNIZ kapalı dikey döngü için gerekir.

        Verilmezlerse (sim yolu) hiçbir şey değişmez — bekçi R34."""
        c = self.cfg
        vx_h, vy_h, vz_h_ned = v_hedef_ned
        vx_o, vy_o, vz_o     = v_olculen_unreal

        # [1] iki hızı da GÖVDE çerçevesine al
        ileri_h, sag_h = self.dunya_govde(vx_h, vy_h, yaw_rad, c.Y_ISARET)
        ileri_o, sag_o = self.dunya_govde(vx_o, vy_o, yaw_rad, c.Y_ISARET)

        # [2] hız hatası -> istenen ivme
        a_ileri = c.K_V * (ileri_h - ileri_o)
        a_sag   = c.K_V * (sag_h   - sag_o)

        # [3] ivme -> çubuk
        pitch_ham = self._ivme_cubuk(a_ileri)
        roll_ham  = self._ivme_cubuk(a_sag)

        # --- DİKEY ---
        vz_yukari = c.Z_ISARET * vz_h_ned          # NED aşağı -> "yukarı"
        if self.dikey is None:
            # SİM YOLU: ölçülmüş iki kollu ters model (yukarıdaki tabloya bak)
            thr_ham = self._vz_cubuk(vz_yukari)
        else:
            # GERÇEK YOL: kapalı döngü. ÖLÇÜLEN düşey hızı da ister.
            # ⚠ Eğim telafisi KOMUT EDİLEN yatıştan hesaplanır, ölçülenden
            #   değil: Angle modunda araç komutu ~0.2 s'de takip eder, yani
            #   komut ölçümün İLERİSİNDEDİR ve ileri besleme için doğru
            #   olan odur (bozucuyu beklemeden telafi etmek).
            import math as _m
            _aci = _m.radians(c.MAX_YATIS_DEG)
            cosy = (_m.cos(pitch_ham * _aci) * _m.cos(roll_ham * _aci)
                    if c.MODEL == "aci" else 1.0)
            thr_ham = self.dikey.hesapla(
                vz_yukari, vz_o, dt if dt else 0.02,
                cos_yatis=cosy, olcum_yasi=olcum_yasi)

        # --- YAW ---
        yaw_ham = _kirp(yaw_rate_hedef_deg / c.YAW_RATE_MAX_DEG)

        # --- eğim sınırı (tek yerde, hepsine) ---
        thr   = _egim_sinirla(thr_ham,   self._onceki["thr"],   c.MAX_DELTA)
        pitch = _egim_sinirla(pitch_ham, self._onceki["pitch"], c.MAX_DELTA)
        roll  = _egim_sinirla(roll_ham,  self._onceki["roll"],  c.MAX_DELTA)
        yaw   = _egim_sinirla(yaw_ham,   self._onceki["yaw"],   c.MAX_DELTA)
        self._onceki = {"thr": thr, "pitch": pitch, "roll": roll, "yaw": yaw}

        # mekanizma kapısı (§5.1): bu sütunlar sıfırsa çevirici çalışmıyordur
        self.tani = {
            "cev_ileri_hata": ileri_h - ileri_o,
            "cev_sag_hata":   sag_h - sag_o,
            "cev_a_ileri":    a_ileri,
            "cev_a_sag":      a_sag,
            "cev_vz_yukari":  vz_yukari,
            "cev_doyum": int(abs(pitch_ham) >= 1.0 or abs(roll_ham) >= 1.0
                             or abs(thr_ham) >= 1.0),
        }
        if self.dikey is not None:
            self.tani.update(self.dikey.tani)
        return thr, pitch, roll, yaw
