#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAHTE YARIŞMA SUNUCUSU — yarışma gününün tam provası, donanımsız

⛔ NİYE VAR: yarışmadan önce ŞUNU kanıtlamak istiyoruz — sunucudan gelen
   hedef konumuna göre güdüm gerçekten o yöne komut üretiyor mu. Gerçek
   sunucu sahada, hedef İHA komitenin elinde; prova yapamıyoruz.
   Bu araç, haberleşme dokümanının ÜÇ UCUNU DA taklit eder ve havada
   uçan bir hedefin BOZULMUŞ GPS'ini yayınlar.

Taklit edilenler (doküman 2026):
    POST /api/giris             kadi/sifre -> çerez
    GET  /api/sunucusaati       sunucu saati
    POST /api/telemetri_gonder  telemetriyi DOĞRULAR + hedef verisi döner
    POST /api/kilitlenme_bilgisi  (gerçekte var mı bilinmiyor — sayar)

⛔ TELEMETRİYİ GERÇEKTEN DENETLER: §7.1'in 14 alanı eksikse 204 döner,
   2 Hz aşılırsa 400 + hata kodu 3 döner. Yani bizim istemcimizin
   dokümana uyduğunu da sınamış oluyoruz.

⭐ HEDEF GERÇEKÇİ BOZULUR (yarışmadaki gibi):
   · konum gürültüsü      (--gurultu, metre)
   · ani sıçrama          (--sicrama saniyede bir, --sicrama-m metre)
   · veri kesintisi       (--kesinti saniyede bir, son paketi tekrarlar)
   · gecikme              (--gecikme saniye; saat_farki alanına da yazılır)

Kullanım:
    python3 araclar/sahte_sunucu.py --merkez 37.9797,41.8443
    python3 araclar/sahte_sunucu.py --gurultu 4 --sicrama 20 --kesinti 30
"""
import argparse
import json
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)

ALANLAR = ("takim_no", "enlem", "boylam", "irtifa", "dikilme", "yonelme",
           "yatis", "hiz", "mod", "kilitlenme", "hedef_x_merkezi",
           "hedef_y_merkezi", "hedef_genislik", "hedef_yukseklik")


class Hedef:
    """Daire çizerek uçan bir İHA. Konumu GERÇEK; bozulma dışarıda eklenir."""

    def __init__(self, enlem, boylam, irtifa, yaricap, hiz):
        self.e0, self.b0 = enlem, boylam
        self.irtifa, self.R, self.V = irtifa, yaricap, hiz
        self.t0 = time.time()
        la = math.radians(enlem)
        self.M = A * (1 - E2) / (1 - E2 * math.sin(la) ** 2) ** 1.5
        self.N = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
        self.cos0 = math.cos(la)

    def konum(self, t=None):
        """(enlem, boylam, irtifa, hiz) — t saniye sonraki GERÇEK konum."""
        t = (time.time() if t is None else t) - self.t0
        w = self.V / self.R                       # açısal hız (rad/s)
        x = self.R * math.cos(w * t)              # kuzey (m)
        y = self.R * math.sin(w * t)              # doğu  (m)
        e = self.e0 + math.degrees(x / self.M)
        b = self.b0 + math.degrees(y / (self.N * self.cos0))
        return e, b, self.irtifa, self.V


class Bozucu:
    """Hedefin GPS'ini yarışmadaki gibi bozar."""

    def __init__(self, gurultu_m, sicrama_sn, sicrama_m, kesinti_sn,
                 kesinti_sure, gecikme_sn):
        self.g = gurultu_m
        self.sicrama_sn, self.sicrama_m = sicrama_sn, sicrama_m
        self.kesinti_sn, self.kesinti_sure = kesinti_sn, kesinti_sure
        self.gecikme = gecikme_sn
        self.t0 = time.time()
        self._son = None
        self.sayac = {"paket": 0, "sicrama": 0, "kesinti": 0}

    def boz(self, hedef):
        gecen = time.time() - self.t0
        # ⛔ KESİNTİ: son paketi TEKRARLA (gerçek jammer da böyle yapar —
        #   yeni veri gelmez, eski değer tekrar tekrar görünür)
        if self.kesinti_sn > 0:
            faz = gecen % self.kesinti_sn
            if faz < self.kesinti_sure and self._son is not None:
                self.sayac["kesinti"] += 1
                return self._son
        # ⛔ GECİKME: hedefin ŞU ANKİ değil, `gecikme` saniye ÖNCEKİ konumu
        e, b, irt, hiz = hedef.konum(time.time() - self.gecikme)
        # gürültü (metreyi dereceye çevirerek)
        if self.g > 0:
            e += math.degrees(random.gauss(0, self.g) / hedef.M)
            b += math.degrees(random.gauss(0, self.g) / (hedef.N * hedef.cos0))
        # ⛔ SIÇRAMA: periyodik, yanal yönde
        if self.sicrama_sn > 0 and (gecen % self.sicrama_sn) < 0.6:
            self.sayac["sicrama"] += 1
            b += math.degrees(self.sicrama_m / (hedef.N * hedef.cos0))
        self.sayac["paket"] += 1
        self._son = (e, b, irt, hiz)
        return self._son


class Sunucu(BaseHTTPRequestHandler):
    hedef = None
    bozucu = None
    kadi = "hamidiye"
    sifre = "Z8vN1cR5tY"
    sayac = {"giris": 0, "telemetri": 0, "red_bicim": 0, "red_hiz": 0,
             "kilit": 0, "saat": 0}
    _son_telem = [0.0]
    _kilit = threading.Lock()
    sessiz = True

    def log_message(self, *a):
        if not Sunucu.sessiz:
            BaseHTTPRequestHandler.log_message(self, *a)

    def _yaz(self, kod, govde=None):
        ham = json.dumps(govde).encode() if govde is not None else b""
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(ham)))
        self.end_headers()
        if ham:
            self.wfile.write(ham)

    @staticmethod
    def _saat():
        t = time.localtime()
        return {"saat": t.tm_hour, "dakika": t.tm_min, "saniye": t.tm_sec,
                "milisaniye": int((time.time() % 1.0) * 1000)}

    def do_GET(self):
        if self.path == "/api/sunucusaati":
            Sunucu.sayac["saat"] += 1
            return self._yaz(200, self._saat())
        self._yaz(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            g = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._yaz(204)

        if self.path == "/api/giris":
            if g.get("kadi") == Sunucu.kadi and g.get("sifre") == Sunucu.sifre:
                Sunucu.sayac["giris"] += 1
                self.send_response(200)
                self.send_header("Set-Cookie", "oturum=1; Path=/")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            return self._yaz(401)

        if self.path == "/api/telemetri_gonder":
            # ⛔ HIZ KAPISI — doküman §7: 2 Hz üzeri 400 + hata kodu 3
            with Sunucu._kilit:
                simdi = time.monotonic()
                aralik = simdi - Sunucu._son_telem[0]
                Sunucu._son_telem[0] = simdi
            if aralik < 0.5:
                Sunucu.sayac["red_hiz"] += 1
                self.send_response(400)
                self.send_header("Content-Length", "1")
                self.end_headers()
                self.wfile.write(b"3")          # hata kodu 3
                return
            # ⛔ BİÇİM DENETİMİ — §7.1'in 14 alanı
            eksik = [k for k in ALANLAR if k not in g]
            if eksik:
                Sunucu.sayac["red_bicim"] += 1
                return self._yaz(204)
            Sunucu.sayac["telemetri"] += 1
            e, b, irt, hiz = Sunucu.bozucu.boz(Sunucu.hedef)
            return self._yaz(200, {
                "sunucu_saati": self._saat(),
                "hedef_iha_verileri": [{
                    "takim_no": 1,
                    "enlem": round(e, 7), "boylam": round(b, 7),
                    "irtifa_ev": round(irt, 1), "hiz": round(hiz, 1),
                    "saat_farki": int(Sunucu.bozucu.gecikme * 1000)}]})

        if self.path == "/api/kilitlenme_bilgisi":
            Sunucu.sayac["kilit"] += 1
            return self._yaz(200, {"ok": True})

        self._yaz(404)


def main():
    a = argparse.ArgumentParser(description="Sahte yarışma sunucusu")
    a.add_argument("--port", type=int, default=10001)
    a.add_argument("--merkez", default="37.9797,41.8443",
                   help="hedefin daire merkezi: enlem,boylam")
    a.add_argument("--irtifa", type=float, default=80.0)
    a.add_argument("--yaricap", type=float, default=200.0)
    a.add_argument("--hiz", type=float, default=20.0)
    a.add_argument("--gurultu", type=float, default=3.0, help="metre (sigma)")
    a.add_argument("--sicrama", type=float, default=25.0, help="kaç sn'de bir")
    a.add_argument("--sicrama-m", type=float, default=40.0)
    a.add_argument("--kesinti", type=float, default=40.0, help="kaç sn'de bir")
    a.add_argument("--kesinti-sure", type=float, default=3.0)
    a.add_argument("--gecikme", type=float, default=1.0, help="saniye")
    a.add_argument("--gurultusuz", action="store_true",
                   help="hiç bozma — saf geometri sınaması")
    a = a.parse_args()

    e0, b0 = (float(x) for x in a.merkez.split(","))
    Sunucu.hedef = Hedef(e0, b0, a.irtifa, a.yaricap, a.hiz)
    if a.gurultusuz:
        Sunucu.bozucu = Bozucu(0, 0, 0, 0, 0, 0)
    else:
        Sunucu.bozucu = Bozucu(a.gurultu, a.sicrama, a.sicrama_m,
                               a.kesinti, a.kesinti_sure, a.gecikme)

    print("=" * 70)
    print("  SAHTE YARIŞMA SUNUCUSU")
    print("=" * 70)
    print("  adres      : http://127.0.0.1:%d" % a.port)
    print("  kullanıcı  : %s" % Sunucu.kadi)
    print("  HEDEF      : %.4f, %.4f merkezli %g m yarıçaplı daire"
          % (e0, b0, a.yaricap))
    print("               %g m irtifa, %g m/s  (tur süresi %.0f s)"
          % (a.irtifa, a.hiz, 2 * math.pi * a.yaricap / a.hiz))
    if a.gurultusuz:
        print("  BOZULMA    : YOK (saf geometri)")
    else:
        print("  BOZULMA    : gürültü %g m · sıçrama %g m/%gs · kesinti %gs/%gs"
              " · gecikme %g s"
              % (a.gurultu, a.sicrama_m, a.sicrama, a.kesinti_sure,
                 a.kesinti, a.gecikme))
    print()
    print("  ⛔ Telemetri BİÇİMİ ve 2 Hz sınırı GERÇEKTEN denetlenir.")
    print("  Ctrl+C ile durur.")
    print("=" * 70)

    s = ThreadingHTTPServer(("0.0.0.0", a.port), Sunucu)

    def rapor():
        while True:
            time.sleep(10)
            c, b = Sunucu.sayac, Sunucu.bozucu.sayac
            print("  [%5.0f s] giriş %d · telemetri %d · red(biçim %d, hız %d)"
                  " · kilit %d   |  sıçrama %d · kesinti %d"
                  % (time.time() - Sunucu.bozucu.t0, c["giris"], c["telemetri"],
                     c["red_bicim"], c["red_hiz"], c["kilit"],
                     b["sicrama"], b["kesinti"]))
    threading.Thread(target=rapor, daemon=True).start()
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        print("\n  kapatıldı. Toplam: %s" % Sunucu.sayac)


if __name__ == "__main__":
    main()
