# -*- coding: utf-8 -*-
"""
================================================================================
HEDEF KAYNAĞI — hedef İHA'nın konumu nereden geliyor
================================================================================
İKİ KAYNAK, TEK BİÇİM. Drone tarafındaki kod, hangisi olduğunu BİLMEZ:

  YARIŞMADA : yarışma sunucusunun `/api/telemetri_gonder` YANITI (1-2 Hz)
  DENEMEDE  : Talon bilgisayarının LAN'a yayınladığı AYNI biçimdeki paket (5 Hz)

⭐ NİYE AYNI BİÇİM: yarışma günü ilk kez denenen bir kod yolu KALMASIN.
   Bugün Talon bilgisayarından gelen paket, yarın sunucudan gelenle
   birebir aynı alanlara sahip; değişen tek şey ADRES.

PAKET (haberleşme dokümanı §7.2):
    {"takim_no": 1, "enlem": 41.5, "boylam": 36.1,
     "irtifa_ev": 38.0, "hiz": 28.5, "saat_farki": 85}

⚠ `irtifa_ev` YER/EV SEVİYESİNE GÖREDİR (deniz seviyesine göre DEĞİL).
  Bizim GPS'imiz AMSL verir. Dönüşüm `konum.YerelCerceve` içinde, tek yerde.

⛔ BAYATLIK — SESSİZ TUZAK: sunucu 1-2 Hz veriyor ve `saat_farki` alanı
   verinin ne kadar eski olduğunu MİLİSANİYE olarak söylüyor. 28 m/s giden
   bir hedef 500 ms'de 14 m yol alır. Bayat paketi taze sanmak, hedefi
   olmadığı yerde aramaktır. Bu yüzden her paketin yaşı tutulur ve
   `MAX_YAS_S` aşılırsa hedef YOK sayılır.
================================================================================
"""
import json
import os
import socket
import threading
import time


class HedefCfg:
    #: Bu yaştan eski paket YOK sayılır.
    #: 1.5 s: 1 Hz'lik sunucuda tek paket kaybını tolere eder, ikisini etmez.
    MAX_YAS_S = float(os.environ.get("DOW_HEDEF_MAX_YAS", 1.5))
    #: LAN yayını (Talon bilgisayarı -> drone bilgisayarı)
    UDP_PORT = int(os.environ.get("DOW_HEDEF_UDP_PORT", 47800))
    #: Hedefin makul hız bandı; dışındaki paket BOZUK sayılır.
    HIZ_MIN, HIZ_MAX = 0.0, 80.0


class HedefKaynagi:
    """Son geçerli hedef paketini yaş denetimiyle sunar. İş parçacığı güvenli."""

    def __init__(self, cfg=HedefCfg):
        self.cfg = cfg
        self._kilit = threading.Lock()
        self._paket = None
        self._t = 0.0
        self.n_paket = 0
        self.n_red = 0
        self.son_red_sebep = ""

    # ------------------------------------------------------------------
    def besle(self, paket, t=None):
        """Yeni hedef paketi. Döner: kabul edildi mi."""
        try:
            e = float(paket["enlem"]); b = float(paket["boylam"])
            irt = float(paket["irtifa_ev"]); hz = float(paket.get("hiz", 0.0))
        except (KeyError, TypeError, ValueError) as ex:
            self.n_red += 1; self.son_red_sebep = "alan: %s" % ex
            return False
        # ⛔ AKLI BAŞINDA DEĞER DENETİMİ: bozuk bir paketi hedef sanmak,
        #   güdümü dünyanın öbür ucuna nişan aldırır.
        if not (-90.0 <= e <= 90.0 and -180.0 <= b <= 180.0):
            self.n_red += 1; self.son_red_sebep = "koordinat aralık dışı"
            return False
        if not (self.cfg.HIZ_MIN <= hz <= self.cfg.HIZ_MAX):
            self.n_red += 1; self.son_red_sebep = "hız aralık dışı: %.1f" % hz
            return False
        with self._kilit:
            self._paket = {"takim_no": paket.get("takim_no"),
                           "enlem": e, "boylam": b, "irtifa_ev": irt,
                           "hiz": hz,
                           "saat_farki": float(paket.get("saat_farki", 0.0))}
            self._t = time.monotonic() if t is None else t
            self.n_paket += 1
        return True

    def son(self):
        """Taze hedef paketi ya da None (bayatsa None)."""
        with self._kilit:
            if self._paket is None:
                return None
            if self._yas_kilitli() > self.cfg.MAX_YAS_S:
                return None
            return dict(self._paket)

    def _yas_kilitli(self):
        """GERÇEK yaş = paketin bize ulaşma yaşı + VERİNİN KENDİ yaşı.

        ⛔⛔ SESSİZ HAYALET TUZAĞI (2026-08-29'da ölçülerek görüldü):
           Yayıncı OLAY GÜDÜMLÜ çalışıyor ama bir de periyodik kalp atışı
           basıyor. Uçakla telsiz bağı koparsa yayıncı SON BİLİNEN konumu
           basmaya DEVAM eder. Paket taze görünür — çünkü az önce geldi —
           ama İÇİNDEKİ VERİ saniyelerce eski olabilir.
           Güdüm o zaman hedefin artık olmadığı bir yere nişan alır.

        `saat_farki` alanı tam bunun için var (haberleşme dokümanı §7.2:
        "Sunucu saati ile verinin zamanı arasındaki fark, milisaniye").
        Yayıncımız da aynı alanı aynı anlamda dolduruyor.

        ⚠ 28 m/s giden bir hedef 500 ms'de 14 m yol alır. Bu alanı yok
          saymak, hedefi 14 m yanlış yerde aramaktır.
        """
        if self._paket is None:
            return 9e9
        ulasma = time.monotonic() - self._t
        veri = float(self._paket.get("saat_farki", 0.0)) / 1000.0
        return ulasma + max(0.0, veri)

    def yas(self):
        with self._kilit:
            return self._yas_kilitli()

    def durum(self):
        s = self.son()
        with self._kilit:
            ham = dict(self._paket) if self._paket else None
            ulasma = (9e9 if self._paket is None
                      else time.monotonic() - self._t)
            veri_yas = (0.0 if self._paket is None
                        else float(self._paket.get("saat_farki", 0.0)) / 1000.0)
        # ⭐ HAM KONUM — BAYAT OLSA BİLE RAPORLANIR (2026-08-29).
        #   `son()` bayat paketi None döndürür; bu DOĞRUdur, güdüm bayat
        #   veriyle nişan almamalı. Ama operatör panelde yalnız "hedef YOK"
        #   görüyordu ve "paket geliyor ama verisi 26 dakikalık" durumunu
        #   ayırt edemiyordu. Ham alanlar GÖSTERİM içindir; güdüm bunları
        #   OKUMAZ — güdümün tek kapısı `son()`tur.
        return {"var": s is not None, "yas": round(self.yas(), 2),
                "ham_enlem": (ham or {}).get("enlem"),
                "ham_boylam": (ham or {}).get("boylam"),
                "ham_irtifa": (ham or {}).get("irtifa_ev"),
                "ham_hiz": (ham or {}).get("hiz"),
                # ⭐ İKİSİ AYRI RAPORLANIR: "paket geliyor ama VERİSİ eski"
                #   durumunu operatör ancak böyle görebilir.
                "yas_ulasma": round(min(ulasma, 999.0), 2),
                "yas_veri": round(veri_yas, 2),
                "n_paket": self.n_paket, "n_red": self.n_red,
                "red_sebep": self.son_red_sebep,
                "hiz": (s or {}).get("hiz"),
                "irtifa_ev": (s or {}).get("irtifa_ev")}


class UdpDinleyici:
    """Talon bilgisayarının LAN yayınını dinler (denemede kullanılır).

    ⛔ NİYE UDP: 5 Hz'lik bir konum akışında TCP'nin yeniden gönderimi
       ZARARLIDIR — kaybolan bir paketin geç gelen kopyası, taze paketin
       önüne geçer ve güdüm eski dünyaya nişan alır. Kaybolan paket
       ATILMALIDIR; bir sonraki 200 ms sonra zaten geliyor.
    """

    def __init__(self, kaynak, port=None, cfg=HedefCfg):
        self.kaynak = kaynak
        self.port = port if port is not None else cfg.UDP_PORT
        self._sok = None
        self._is = None
        self._calisiyor = False
        self.hata = None

    def basla(self):
        try:
            self._sok = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sok.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sok.bind(("", self.port))
            self._sok.settimeout(0.5)
        except Exception as e:
            self.hata = "%s: %s" % (type(e).__name__, e)
            return False
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True,
                                    name="hedef-udp")
        self._is.start()
        return True

    def dur(self):
        self._calisiyor = False
        try:
            if self._sok:
                self._sok.close()
        except Exception:
            pass

    def _dongu(self):
        while self._calisiyor:
            try:
                veri, _ = self._sok.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception:
                break
            try:
                d = json.loads(veri.decode("utf-8"))
            except Exception:
                continue
            # Sunucu biçimi liste halinde gelir; tek hedef de kabul edilir.
            if isinstance(d, dict) and "hedef_iha_verileri" in d:
                for h in d["hedef_iha_verileri"]:
                    self.kaynak.besle(h)
            elif isinstance(d, list):
                for h in d:
                    self.kaynak.besle(h)
            elif isinstance(d, dict):
                self.kaynak.besle(d)
