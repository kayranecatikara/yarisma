# -*- coding: utf-8 -*-
"""
================================================================================
YARIŞMA SUNUCUSU İSTEMCİSİ — Teknofest Haberleşme Dokümanı 2026
================================================================================
Kaynak: "Savaşan İHA Avcı Drone — Haberleşme Dokümanı", REST/HTTP+JSON.

  POST /api/giris             {"kadi","sifre"}
  GET  /api/sunucusaati
  POST /api/telemetri_gonder  bizim telemetrimiz -> YANIT: hedef İHA verileri

⛔⛔ HIZ SINIRI — DOKÜMANIN AÇIK KURALI:
   "Takımlar EN AZ 1 Hz ile göndermelidir. **2 Hz ÜZERİNDE gönderilen
   paketler 400 durum kodu ile 3 hata kodu ile cevaplanır.**"
   Yani hızlı göndermek bizi cezalandırır. Gönderim hızı KODDA SINIRLIDIR
   ve varsayılan 1.5 Hz'dir (iki sınırın ortası, saat kaymasına pay).

⛔ KİLİTLENME PAKETİ (§8): her başarılı kilitlenmeden SONRA, kilitlenmenin
   BİTİŞ zamanıyla, ve her kilit için YALNIZCA BİR paket. Zaman SUNUCU
   SAATİ türünde olmalı — bizim yerel saatimiz değil.

⚠ AĞ HATASI UÇUŞU DURDURMAZ: bu istemci hiçbir zaman güdüm döngüsünü
  bloke etmez. Kendi iş parçacığında koşar; sunucu düşerse uçuş sürer.
================================================================================
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request


class SunucuCfg:
    ADRES   = os.environ.get("DOW_SUNUCU", "http://127.0.0.1:5000")
    KADI    = os.environ.get("DOW_SUNUCU_KADI", "")
    SIFRE   = os.environ.get("DOW_SUNUCU_SIFRE", "")
    TAKIM_NO = int(os.environ.get("DOW_TAKIM_NO", "0"))
    #: Gönderim hızı. ⛔ 2.0'ı ASLA aşma (doküman §7: 400 + hata kodu 3).
    GONDER_HZ = float(os.environ.get("DOW_SUNUCU_HZ", 1.5))
    ZAMAN_ASIMI = float(os.environ.get("DOW_SUNUCU_ASIM", 2.0))


class SunucuIstemcisi:
    """Yarışma sunucusuyla haberleşme. Kendi iş parçacığında koşar."""

    def __init__(self, hedef_kaynagi, telemetri_saglayici, cfg=SunucuCfg):
        self.cfg = cfg
        self.hedef = hedef_kaynagi
        self.telem = telemetri_saglayici      # fn() -> telemetri sözlüğü
        self._cerez = None
        self._calisiyor = False
        self._is = None
        self.baglandi = False
        self.son_hata = ""
        self.sunucu_saati = None
        self.sayac = {"gonderilen": 0, "hata": 0, "kilit_paketi": 0,
                      "hiz_ihlali": 0}
        self._son_gonderim = 0.0
        self._kilit_kuyrugu = []
        self._kuyruk_kilidi = threading.Lock()

    # ---------------- HTTP ----------------
    def _istek(self, yol, govde=None, yontem=None):
        url = self.cfg.ADRES.rstrip("/") + yol
        veri = None if govde is None else json.dumps(govde).encode("utf-8")
        r = urllib.request.Request(url, data=veri,
                                   method=yontem or ("POST" if veri else "GET"))
        r.add_header("Content-Type", "application/json")
        if self._cerez:
            r.add_header("Cookie", self._cerez)
        with urllib.request.urlopen(r, timeout=self.cfg.ZAMAN_ASIMI) as y:
            c = y.headers.get("Set-Cookie")
            if c:
                self._cerez = c.split(";")[0]
            ham = y.read()
            return (json.loads(ham.decode("utf-8")) if ham else {})

    def giris(self):
        try:
            self._istek("/api/giris", {"kadi": self.cfg.KADI,
                                       "sifre": self.cfg.SIFRE})
            self.baglandi = True
            self.son_hata = ""
            return True, "giriş başarılı"
        except urllib.error.HTTPError as e:
            self.baglandi = False
            self.son_hata = "HTTP %d: %s" % (e.code, self._kod_acikla(e.code))
            return False, self.son_hata
        except Exception as e:
            self.baglandi = False
            self.son_hata = "%s: %s" % (type(e).__name__, e)
            return False, self.son_hata

    @staticmethod
    def _kod_acikla(kod):
        return {200: "başarılı", 204: "paket BİÇİMİ yanlış",
                400: "istek hatalı/geçersiz (hız aşımıysa hata kodu 3)",
                401: "kimliksiz erişim — oturum açılmamış",
                403: "yetkisiz erişim", 404: "geçersiz URL",
                500: "sunucu içi hata"}.get(kod, "bilinmeyen kod")

    def saati_al(self):
        try:
            self.sunucu_saati = self._istek("/api/sunucusaati")
            return self.sunucu_saati
        except Exception as e:
            self.son_hata = "saat: %s" % e
            return None

    # ---------------- kilitlenme ----------------
    def kilit_bildir(self, bitis_saati=None, otonom=True):
        """Bir kilitlenme bitti — sunucuya bildir (§8).

        ⛔ HER KİLİT İÇİN YALNIZCA BİR PAKET. Kuyruğa alınır ve iş
           parçacığı gönderir; ağ yavaşsa güdüm döngüsü beklemez.
        """
        s = bitis_saati or self.sunucu_saati or {}
        paket = {"kilitlenmeBitisZamani": {
                     "saat": int(s.get("saat", 0)),
                     "dakika": int(s.get("dakika", 0)),
                     "saniye": int(s.get("saniye", 0)),
                     "milisaniye": int(s.get("milisaniye", 0))},
                 "otonom_kilitlenme": 1 if otonom else 0}
        with self._kuyruk_kilidi:
            self._kilit_kuyrugu.append(paket)
        return paket

    # ---------------- döngü ----------------
    def basla(self):
        if self._calisiyor:
            return
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True,
                                    name="yarisma-sunucusu")
        self._is.start()

    def dur(self):
        self._calisiyor = False
        if self._is:
            self._is.join(timeout=2.0)

    def _dongu(self):
        periyot = 1.0 / max(0.1, min(2.0, self.cfg.GONDER_HZ))
        while self._calisiyor:
            t0 = time.monotonic()
            # ⛔ HIZ KAPISI: doküman 2 Hz üstünü CEZALANDIRIYOR. Bu denetim
            #   periyodun yanında İKİNCİ bir güvencedir (zamanlayıcı kayarsa).
            if (t0 - self._son_gonderim) < 0.5:
                self.sayac["hiz_ihlali"] += 1
                time.sleep(0.05)
                continue
            try:
                yanit = self._istek("/api/telemetri_gonder", self.telem())
                self._son_gonderim = t0
                self.sayac["gonderilen"] += 1
                self.baglandi = True
                if isinstance(yanit, dict):
                    if "sunucu_saati" in yanit:
                        self.sunucu_saati = yanit["sunucu_saati"]
                    for h in yanit.get("hedef_iha_verileri", []) or []:
                        self.hedef.besle(h)
            except urllib.error.HTTPError as e:
                self.sayac["hata"] += 1
                self.son_hata = "HTTP %d: %s" % (e.code, self._kod_acikla(e.code))
                if e.code == 401:
                    self.giris()
            except Exception as e:
                self.sayac["hata"] += 1
                self.son_hata = "%s: %s" % (type(e).__name__, e)
            # kilit kuyruğunu boşalt
            with self._kuyruk_kilidi:
                kuyruk, self._kilit_kuyrugu = self._kilit_kuyrugu, []
            for p in kuyruk:
                try:
                    self._istek("/api/kilitlenme_bilgisi", p)
                    self.sayac["kilit_paketi"] += 1
                except Exception as e:
                    self.son_hata = "kilit paketi: %s" % e
            uyku = periyot - (time.monotonic() - t0)
            time.sleep(uyku if uyku > 0 else 0.01)

    def durum(self):
        return {"baglandi": self.baglandi, "adres": self.cfg.ADRES,
                "hata": self.son_hata, "saat": self.sunucu_saati,
                **self.sayac}
