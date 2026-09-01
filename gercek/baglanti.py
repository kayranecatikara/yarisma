# -*- coding: utf-8 -*-
"""
================================================================================
GERÇEK ARAÇ BAĞLANTISI — araç sözleşmesinin donanım karşılığı
================================================================================
`gercek/arayuz.py` sözleşmesini GERÇEK drone için karşılar. `dow/ana.py::Beyin`
buna takıldığında güdüm yasasında TEK SATIR değişmez:

    Beyin(baglanti=GercekBaglanti(bag, cerceve))

VERİ AKIŞI
    CRSF telemetri (ELRS) ─┬─ GPS      -> enlem/boylam/irtifa/yer hızı/ROTA
                           ├─ ATTITUDE -> roll/pitch/yaw (radyan)
                           ├─ VARIO    -> düşey hız
                           └─ LINK     -> bağ sağlığı (emniyet)
                                  ↓
                       `konum.YerelCerceve` ile METREYE
                                  ↓
                      konum() / yonelim() / hiz_vektoru()

--------------------------------------------------------------------------------
⛔ SİMDE OLMAYAN ÜÇ ŞEY — HER BİRİ BİR TUZAK
--------------------------------------------------------------------------------
1) TELEMETRİ AYRI AYRI VE FARKLI HIZLARDA GELİR.
   Simde `get_telemetry()` tek atımda tutarlı bir görüntü veriyordu.
   Burada GPS ~5-10 Hz, ATTITUDE ~10-30 Hz, VARIO ~5-10 Hz ayrı ayrı düşer.
   Her alanın KENDİ zaman damgası tutulur; "en son ne geldiyse o" demek,
   farklı anlara ait parçaları tek bir duruş sanmaktır.

2) DONMUŞ TELEMETRİ HATA VERMEZ.
   Link kopunca son paket elde kalır ve sonsuza dek "geçerli" görünür.
   DoW'da bu tam olarak yaşandı: "40+ saniye donmuş veriyle uçtuk".
   `canli()` bu yüzden SON PAKETİN YAŞINA bakar, varlığına değil.

3) HIZ VEKTÖR OLARAK GELMEZ.
   CRSF yer hızını BÜYÜKLÜK + ROTA olarak verir. Vektöre çevirmek
   `konum.yer_hizindan_vektor`ün işi.
   ⛔ ROTA (gidiş yönü) ile YAW (burun yönü) farklıdır ve rüzgârda ayrışır.
      Hız vektörü ROTA'dan, gövde dönüşümü YAW'dan hesaplanır.

--------------------------------------------------------------------------------
⛔ YARIŞMA KURALI (CLAUDE.md §10)
--------------------------------------------------------------------------------
`truth()` DAİMA None döner — gerçekte böyle bir kanal yoktur.
`hedef_konum_bozuk()` hedefi YARIŞMA SUNUCUSUNDAN (ya da denemede Talon
bilgisayarından) alır ve YALNIZ görsel temas yokken çağrılır; kuralı
`dow/ana.py` yapısal olarak uygular.
================================================================================
"""
import math
import os
import time

from . import crsf
from .arayuz import AracArayuzu
from .gnss_filtre import HedefSuzgeci
from .konum import YerelCerceve, yer_hizindan_vektor


class BaglantiCfg:
    #: Bir telemetri alanı bu kadar bayatsa YOK sayılır.
    #: 1.0 s: 5 Hz'lik bir kanalda 5 paket kaybı demektir — gerçek kopukluk.
    ALAN_MAX_YAS_S = float(os.environ.get("DOW_BAG_ALAN_YAS", 1.0))
    #: `canli()` için: HİÇBİR paket bu süredir gelmiyorsa bağ ÖLÜ.
    CANLI_MAX_YAS_S = float(os.environ.get("DOW_BAG_CANLI_YAS", 1.5))
    #: Kökeni kurmak için gereken en az uydu sayısı.
    #: ⛔ 6 uydu ile alınan bir fix 20-30 m kayabilir; kökeni oraya kurmak
    #:   BÜTÜN uçuşu o kadar kaydırır. 10, dışarıda kolayca sağlanır.
    MIN_UYDU = int(os.environ.get("DOW_BAG_MIN_UYDU", 10))
    #: Link kalitesi bu yüzdenin altındaysa uyarı (emniyet katmanı okur).
    LINK_LQ_UYARI = float(os.environ.get("DOW_BAG_LQ_UYARI", 70.0))


class GercekBaglanti(AracArayuzu):
    """CRSF telemetrisi + CRSF komutu ile araç sözleşmesini karşılar.

    `komut_sureci` verilirse komutlar ORAYA yazılır (hakemden geçer);
    verilmezse doğrudan bağa yazılır (YALNIZ tezgâh/yer sınamaları için).
    ⛔ SAHADA DAİMA `komut_sureci` verilir — yoksa pilot devralamaz.
    """

    def __init__(self, bag, komut_sureci=None, cerceve=None, cfg=BaglantiCfg,
                 hedef_kaynak=None):
        self.bag = bag
        self.komut_sureci = komut_sureci
        self.cerceve = cerceve if cerceve is not None else YerelCerceve()
        self.cfg = cfg
        self.hedef_kaynak = hedef_kaynak      # `hedef.py`; None ise hedef yok
        # ⛔ GNSS SÜZGECİ — yarışmada hedef GPS'i KASTEN BOZULMUŞ gelir.
        #   Varsayılan KAPALI (`DOW_GNSS_FILTRE=0`); kapalıyken ham konum
        #   aynen döner ve davranış bit bit eskisidir (bekçi R122).
        self.gnss_suzgec = HedefSuzgeci()
        # --- her alanın KENDİ zaman damgası (tuzak 1) ---
        self._alan = {}          # ad -> (deger_sozlugu, t)
        self._son_paket_t = 0.0
        self.n_guncelleme = 0
        self.uyari = []

    # ------------------------------------------------------------------
    #  TELEMETRİ POMPASI — kontrol döngüsünün her tikinde çağrılır
    # ------------------------------------------------------------------
    def pompala(self):
        """Seri porttan geleni oku ve alanları tazele. Bloke ETMEZ.

        Döner: bu çağrıda tazelenen alanların adları (teşhis için).
        """
        d = self.bag.oku()
        if not d:
            return ()
        simdi = time.monotonic()
        for ad, deger in d.items():
            self._alan[ad] = (deger, simdi)
        self._son_paket_t = simdi
        self.n_guncelleme += 1
        return tuple(d.keys())

    def _al(self, ad, alan=None, varsayilan=None):
        """Bir telemetri alanını YAŞ DENETİMİYLE oku. Bayatsa `varsayilan`."""
        girdi = self._alan.get(ad)
        if girdi is None:
            return varsayilan
        deger, t = girdi
        if (time.monotonic() - t) > self.cfg.ALAN_MAX_YAS_S:
            return varsayilan
        return deger if alan is None else deger.get(alan, varsayilan)

    def yas(self, ad):
        """Bir alanın yaşı (saniye). Hiç gelmediyse büyük bir sayı."""
        girdi = self._alan.get(ad)
        if girdi is None:
            return 9e9
        return time.monotonic() - girdi[1]

    # ==================================================================
    #  KATMAN 1 — GÜDÜM
    # ==================================================================
    def canli(self):
        """⛔ 'Son veri var mı' DEĞİL, 'veri AKIYOR mu'.

        Donmuş telemetri hata vermez; DoW'da 40+ saniye donmuş veriyle
        uçuldu. Burada bağ, SON PAKETİN YAŞINA göre ölü sayılır.
        """
        if not getattr(self.bag, "acik", False):
            return False
        if self._son_paket_t <= 0.0:
            return False
        return (time.monotonic() - self._son_paket_t) <= self.cfg.CANLI_MAX_YAS_S

    def konum(self):
        """(kuzey, doğu, yukarı) METRE. Fix yoksa/bayatsa (0,0,0) DEĞİL — hata.

        ⛔ SESSİZ (0,0,0) DÖNMEK ÖLÜMCÜL OLURDU: güdüm kendini kalkış
           noktasında sanır ve hedefe doğru dev bir hata görür.
           Bunun yerine `canli()` zaten False olur ve Beyin tiki atlar.
        """
        g = self._al("gps")
        if g is None or not self.cerceve.hazir:
            return (0.0, 0.0, 0.0)
        return self.cerceve.metreye(g["enlem"], g["boylam"],
                                    irtifa_amsl=g["irtifa_amsl_m"])

    def gps_konum(self):
        """Aracın HAM GPS enlem/boylamı (derece) — ya da None (bayat/yok).

        ⛔ NİYE VAR (2026-09-01, haberleşme testinde hakemler bildirdi):
          yarışma sunucusuna `iha_enlem = 0.0, iha_boylam = 0.0`
          gidiyordu. Konumu GPS -> yerel metre -> derece diye GİDİP
          GELDİRİYORDUK; panelde KÖKEN KUR'a basılmadığı için çerçeve
          hazır değildi ve dönüş sessizce (0,0) veriyordu — oysa aracın
          enlem/boylamı o sırada elimizdeydi (16 uydu, taze çerçeve).
          Yerel metre çerçevesi GÜDÜMÜN iç aracıdır; DIŞARIYA rapor
          ettiğimiz konumun ona bağlı olması için hiçbir sebep yok.
        """
        g = self._al("gps")
        if not g:
            return None
        try:
            return float(g["enlem"]), float(g["boylam"])
        except (KeyError, TypeError, ValueError):
            return None

    def rota(self):
        """GPS ROTASI (yer üstünde gidilen yön, derece) + yer hızı (m/s).

        ⛔ ROTA ≠ BURUN — VE BU BİR TEŞHİS ARACIDIR.
           `rota` GPS'ten türetilir: aracın GERÇEKTEN gittiği yön.
           `yonelim()[2]` (yaw) ise ATTITUDE çerçevesinden gelen BURUN yönü.
           Çok rotorlu araç yan uçabildiği için ikisi genelde AYRIŞIR.

           ⭐ AMA ARAÇ DÜZ İLERİ GİDERKEN ÇAKIŞMALIDIR. Çakışmıyorsa iki
             ihtimal var, ikisi de gövde dönüşümünü bozar:
               (a) pusula (QMC5883) bozuk/kalibresiz -> yaw kayıyor
               (b) `attitude.yaw` aslında ROTA'yı taşıyor — rehber "GPS
                   yoksa heading" diyor (bkz. skydagger.py başlığı). O
                   hâlde yan uçarken yaw yalan söyler.
           Bu ayrım ÖLÇÜLMEMİŞTİ; panel artık ikisini yan yana gösteriyor.

        ⚠ GÜDÜM BUNU OKUMAZ. Yalnız panel/teşhis içindir.
        Döner: (rota_deg, yer_hizi_ms) ya da None (bayat/yok).
        """
        g = self._al("gps")
        if not g:
            return None
        try:
            return float(g["rota_deg"]), float(g["yer_hizi_ms"])
        except (KeyError, TypeError, ValueError):
            return None

    def yonelim(self):
        """(roll, pitch, yaw) RADYAN — doğrudan CRSF ATTITUDE."""
        a = self._al("durus")
        if a is None:
            return (0.0, 0.0, 0.0)
        return (a["roll_rad"], a["pitch_rad"], a["yaw_rad"])

    def hiz_vektoru(self):
        """(v_kuzey, v_doğu, v_yukarı) m/s.

        ⛔ ROTA'DAN hesaplanır, YAW'dan DEĞİL. Yan rüzgârda araç burnunun
           baktığı yere gitmez; hız vektörünü burundan türetmek, rüzgâr
           kadar sistematik hata demektir.
        """
        g = self._al("gps")
        v = self._al("vario", "dusey_hiz_ms", 0.0) or 0.0
        if g is None:
            return (0.0, 0.0, float(v))
        return yer_hizindan_vektor(g["yer_hizi_ms"], g["rota_deg"], v)

    def komut(self, throttle, pitch, roll, yaw, arm=True):
        """⛔ `arm` YOK SAYILIR — arm daima pilottan gelir (komut.py R35).

        İmzada duruyor çünkü sözleşme öyle; ama gerçek araçta güdümün arm
        yetkisi YOKTUR. Hakem (KomutSureci) arm'ı pilotun anahtarından alır.
        """
        if self.komut_sureci is not None:
            self.komut_sureci.otonom_yaz(throttle, pitch, roll, yaw)
            return
        # ⚠ YALNIZ TEZGÂH: hakem yokken doğrudan yazmak, pilotun devralma
        #   yolunu atlamak demektir. Sahada ASLA bu dala girilmez.
        self.bag.rc_gonder(throttle, pitch, roll, yaw, arm=False)

    def hedef_konum_bozuk(self):
        """Hedefin yerel konumu (m). ⛔ YALNIZ görsel temas YOKKEN çağrılır."""
        if self.hedef_kaynak is None or not self.cerceve.hazir:
            return None
        h = self.hedef_kaynak.son()
        if h is None:
            return None
        ham = self.cerceve.metreye(h["enlem"], h["boylam"],
                                   irtifa_yerden=h["irtifa_ev"])
        # ⛔ SÜZGEÇ YEREL METRİK ÇERÇEVEDE ÇALIŞIR — enlem/boylamda değil.
        #   Derece cinsinden mesafeler enlemle ölçeklenir ve Kalman'ın
        #   doğrusal varsayımlarını bozar. Önce metreye, sonra süzgece.
        return self.gnss_suzgec.suz(ham)

    def truth(self):
        """⛔ GERÇEKTE BÖYLE BİR KANAL YOK. Daima None (bekçi R10/R43)."""
        return None

    # ==================================================================
    #  KATMAN 2 — KOŞU/KAYIT
    # ==================================================================
    def baglan(self, deneme=5, bekle=1.0):
        for _ in range(deneme):
            if self.bag.ac():
                return True
            time.sleep(bekle)
        return False

    def yeniden_bagla(self, deneme=6):
        """⛔ SİMDEN FARKLI: burada soket yeniden açılmaz, seri port açılır
        ve İÇ DURUM SIFIRLANIR. Bayat alanları taşımak, link geri gelince
        eski dünyayla uçmak demektir."""
        self.bag.kapat()
        self._alan.clear()
        self._son_paket_t = 0.0
        return self.baglan(deneme=deneme)

    def kapat(self):
        """Aracı KONTROLSÜZ BIRAKMA (CLAUDE.md §9).

        ⛔ NÖTR GÖNDERİP KAPATMAK BURADA YANLIŞ OLUR: nötr çubuk, havadaki
           bir quad için "düz uç" demektir, "in" değil. Doğru kapanış,
           otonomu bırakıp PİLOTA devretmektir; araç yerdeyse zaten
           pilot disarm eder.
        """
        if self.komut_sureci is not None:
            self.komut_sureci.kip_sec("MANUEL")
        self.bag.kapat()

    def hiz(self):
        g = self._al("gps")
        return float(g["yer_hizi_ms"]) if g else 0.0

    def hedef_yonelim(self):
        """⛔ Yarışma sunucusu hedefin YÖNELİMİNİ vermez. Daima None."""
        return None

    # ==================================================================
    #  KURULUM / SAĞLIK
    # ==================================================================
    def kokeni_kur(self, zorla=False):
        """Yerel kökeni GPS'ten kur. Araç YERDEYKEN, kalkıştan ÖNCE.

        Döner: (basarili, mesaj)
        """
        g = self._al("gps")
        if g is None:
            return False, "GPS telemetrisi gelmiyor (CRSF GPS çerçevesi yok)"
        if g["uydu"] < self.cfg.MIN_UYDU and not zorla:
            return False, ("uydu sayısı yetersiz: %d (en az %d). Kökeni zayıf "
                           "bir fix'e kurmak BÜTÜN uçuşu o kadar kaydırır."
                           % (g["uydu"], self.cfg.MIN_UYDU))
        self.cerceve.kokeni_kur(g["enlem"], g["boylam"], g["irtifa_amsl_m"])
        return True, ("köken kuruldu: %.7f, %.7f, %.1f m AMSL (%d uydu)"
                      % (g["enlem"], g["boylam"], g["irtifa_amsl_m"], g["uydu"]))

    def saglik(self):
        """Emniyet katmanının ve panelin okuduğu tek sağlık özeti.

        ⭐ PİL VE LİNK AYRINTISI (2026-08-29) — telemetri bunları ZATEN
          çözüyordu (`crsf.py`: gerilim_v, pil_yuzde, akim_a, tuketim_mah,
          yukari/asagi lq/rssi/snr) ama panele HİÇ çıkmıyordu. Operatör
          drone'un bataryasını GÖREMEDEN uçuyordu; Talon arayüzünde bu
          bilgi vardı, burada yoktu.
        """
        g = self._al("gps"); L = self._al("link"); P = self._al("pil")
        return {
            "canli": self.canli(),
            "koken": self.cerceve.hazir,
            "uydu": (g or {}).get("uydu", 0),
            "yas_gps": round(self.yas("gps"), 3),
            "yas_durus": round(self.yas("durus"), 3),
            "yas_vario": round(self.yas("vario"), 3),
            "link_lq": (L or {}).get("yukari_lq", -1),
            "link_rssi": (L or {}).get("yukari_rssi_dbm", 0),
            # --- link ayrıntısı: hangi yön zayıflıyor, hangi RF kipi ---
            "link_asagi_lq": (L or {}).get("asagi_lq", -1),
            "link_snr": (L or {}).get("yukari_snr"),
            "link_rf_kipi": (L or {}).get("rf_kipi"),
            "yas_link": round(self.yas("link"), 3),
            # --- pil: uçuşun en kritik göstergesi ---
            "pil_v": (P or {}).get("gerilim_v"),
            "pil_yuzde": (P or {}).get("pil_yuzde"),
            "pil_akim": (P or {}).get("akim_a"),
            "pil_mah": (P or {}).get("tuketim_mah"),
            "yas_pil": round(self.yas("pil"), 3),
            "crc_hata": self.bag.cozucu.n_crc_hata,
            "cerceve": self.bag.cozucu.n_cerceve,
        }
