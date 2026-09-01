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

# ⛔ SUNUCUNUN GERÇEK ŞEMASI (komiteden gelen C# sınıfı), PDF'inki DEĞİL.
ALANLAR = ("takim_numarasi", "iha_enlem", "iha_boylam", "iha_irtifa",
           "iha_dikilme", "iha_yonelme", "iha_yatis", "iha_hiz",
           "iha_mod", "iha_kilitlenme", "hedef_merkez_X", "hedef_merkez_Y",
           "hedef_genislik", "hedef_yukseklik")


class Hedef:
    """Hedef İHA'nın GERÇEK konumu. Bozulma dışarıda eklenir.

    ⭐ MERKEZ SONRADAN KURULUR (--merkez oto, VARSAYILAN).
       Sahada elle koordinat girmek, sahayı değiştirdiğimiz anda hedefi
       kilometrelerce öteye koymak demekti. Bunun yerine AVCI DRONUN
       kendi bildirdiği ilk geçerli konum merkez yapılır; hedef bizden
       `uzaklik` metre ötede doğar. Hangi sahada olursak olalım doğru.

    DESENLER — hangi soruyu sorduğuna göre seç:
      "rastgele" : hedef her `degisim` saniyede RASTGELE bir kerterize
                   IŞINLANIR, o dönem boyunca sabit bir rotada uçar.
                   ⭐ "drone hedefe doğru yöneliyor mu" SORUSUNUN TESTİ:
                   ışınlanmadan sonra avcının burnunu yeni kerterize
                   çevirip çevirmediğine bakılır.
      "sabit"    : tek bir kerteriz/uzaklıkta durur. En sade geometri.
      "daire"    : merkez etrafında daire çizer (eski davranış).
    """

    def __init__(self, desen="rastgele", irtifa=80.0, uzaklik=250.0,
                 kerteriz=90.0, hiz=15.0, degisim=45.0, yaricap=200.0,
                 tohum=1):
        self.desen = desen
        self.irtifa, self.uzaklik, self.kerteriz = irtifa, uzaklik, kerteriz
        self.V, self.degisim, self.R = hiz, degisim, yaricap
        self.tohum = tohum
        self.t0 = time.time()
        self.hazir = False
        self.e0 = self.b0 = None
        self.M = self.N = self.cos0 = None
        self._donem = -1
        self._donem_bilgi = None

    def merkez_kur(self, enlem, boylam):
        """Referans noktayı kur — hedef bundan sonra var olur."""
        la = math.radians(enlem)
        self.e0, self.b0 = enlem, boylam
        # Meridyen (M) ve dik kesit (N) eğrilik yarıçapları: metre farkını
        # derece farkına çevirmenin doğru yolu. Düz "1 derece = 111 km"
        # yaklaşımı boylamda enleme göre şaşar.
        self.M = A * (1 - E2) / (1 - E2 * math.sin(la) ** 2) ** 1.5
        self.N = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
        self.cos0 = math.cos(la)
        self.t0 = time.time()
        self._donem = -1
        self.hazir = True

    def _dereceye(self, x, y):
        """kuzey x / doğu y metre -> (enlem, boylam) derece"""
        return (self.e0 + math.degrees(x / self.M),
                self.b0 + math.degrees(y / (self.N * self.cos0)))

    def _donemi_sec(self, gecen):
        """rastgele desen: (kerteriz, uzaklık, rota) — dönem başına SABİT.

        Tohumu dönem numarasından türetiyoruz ki değer dönem içinde
        titremesin: aynı dönemde her çağrı aynı sayıyı versin.
        """
        d = int(gecen / self.degisim) if self.degisim > 0 else 0
        if d != self._donem:
            rng = random.Random(self.tohum + d * 7919)
            self._donem = d
            self._donem_bilgi = (rng.uniform(0.0, 360.0),
                                 rng.uniform(self.uzaklik * 0.6,
                                             self.uzaklik * 1.4),
                                 rng.uniform(0.0, 360.0))
        return self._donem_bilgi

    def nerede(self):
        """Şu anki dönemin (kerteriz°, uzaklık m) özeti — rapor için."""
        if not self.hazir:
            return None
        if self.desen == "sabit":
            return self.kerteriz, self.uzaklik
        if self.desen == "daire":
            return None
        k, u, _ = self._donemi_sec(time.time() - self.t0)
        return k, u

    def konum(self, t=None):
        """(enlem, boylam, irtifa, hiz) — ya da merkez yoksa None."""
        if not self.hazir:
            return None
        t = (time.time() if t is None else t) - self.t0
        if self.desen == "daire":
            w = self.V / self.R                   # açısal hız (rad/s)
            x, y = self.R * math.cos(w * t), self.R * math.sin(w * t)
            hiz = self.V
        elif self.desen == "sabit":
            k = math.radians(self.kerteriz)
            x, y = self.uzaklik * math.cos(k), self.uzaklik * math.sin(k)
            hiz = 0.0
        else:                                     # "rastgele"
            kert, uzak, rota = self._donemi_sec(t)
            icinde = t - (int(t / self.degisim) * self.degisim
                          if self.degisim > 0 else 0.0)
            k, r = math.radians(kert), math.radians(rota)
            x = uzak * math.cos(k) + self.V * icinde * math.cos(r)
            y = uzak * math.sin(k) + self.V * icinde * math.sin(r)
            hiz = self.V
        e, b = self._dereceye(x, y)
        return e, b, self.irtifa, hiz


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
        # ⛔ MERKEZ HENÜZ KURULMADI: hedef YOKTUR. Uydurma bir konum
        #   döndürmek, güdüme "hedef şurada" diye yalan söylemektir.
        if not hedef.hazir:
            return None
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
    hedef_takim = 1
    sayac = {"giris": 0, "telemetri": 0, "red_bicim": 0, "red_hiz": 0,
             "kilit": 0, "saat": 0, "merkez_bekle": 0}
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
            # ⭐ MERKEZİ AVCI DRONUN KENDİ KONUMUNDAN KUR (--merkez oto).
            #   (0,0) gelen paket GEÇERLİ SAYILMAZ: o, köken kurulmadan
            #   ya da GPS fix'siz gönderilen paketin imzasıdır — tam da
            #   2026-09-01'de hakemlerin "full 0 basıyorsunuz" dediği hâl.
            if not Sunucu.hedef.hazir:
                try:
                    e0 = float(g.get("iha_enlem") or 0.0)
                    b0 = float(g.get("iha_boylam") or 0.0)
                except (TypeError, ValueError):
                    e0 = b0 = 0.0
                if abs(e0) > 1e-3 and abs(b0) > 1e-3:
                    Sunucu.hedef.merkez_kur(e0, b0)
                    print("  ⭐ MERKEZ KURULDU — avcı dronun bildirdiği konum:"
                          " %.6f, %.6f" % (e0, b0))
                else:
                    Sunucu.sayac["merkez_bekle"] += 1
                    return self._yaz(200, {"sunucusaati": self._saat(),
                                           "konumBilgileri": []})
            bozuk = Sunucu.bozucu.boz(Sunucu.hedef)
            if bozuk is None:
                return self._yaz(200, {"sunucusaati": self._saat(),
                                       "konumBilgileri": []})
            e, b, irt, hiz = bozuk
            # ⛔⛔ YANIT ŞEMASI = SUNUCUNUN GERÇEĞİ, PDF'İNKİ DEĞİL.
            #   (2026-09-01, ham yanıt basılarak görüldü.) Eskiden burada
            #   PDF adları vardı: `sunucu_saati` / `hedef_iha_verileri` /
            #   `enlem` / `boylam` / `irtifa_ev` / `hiz` / `saat_farki`.
            #   `hedef.py` ikisini de kabul ettiği için prova PATLAMAZDI —
            #   sessizce YARIŞMADAKİNDEN BAŞKA bir kod yolunu sınardık.
            #   Provanın tek anlamı yarışmanın aynısı olması.
            return self._yaz(200, {
                "sunucusaati": self._saat(),
                "konumBilgileri": [{
                    "takim_numarasi": Sunucu.hedef_takim,
                    "iha_enlem": round(e, 7), "iha_boylam": round(b, 7),
                    "iha_irtifa": round(irt, 1), "iha_hizi": round(hiz, 1),
                    "zaman_farki": int(Sunucu.bozucu.gecikme * 1000)}]})

        if self.path == "/api/kilitlenme_bilgisi":
            Sunucu.sayac["kilit"] += 1
            return self._yaz(200, {"ok": True})

        self._yaz(404)


def main():
    a = argparse.ArgumentParser(description="Sahte yarışma sunucusu")
    a.add_argument("--port", type=int, default=10001)
    a.add_argument("--merkez", default="oto",
                   help="referans nokta: 'oto' (VARSAYILAN — avcı dronun "
                        "kendi bildirdiği ilk konum) ya da enlem,boylam")
    a.add_argument("--desen", default="rastgele",
                   choices=("rastgele", "sabit", "daire"),
                   help="rastgele = her --degisim sn'de yeni kerterize "
                        "ışınlanır (YÖNELME TESTİ); sabit = tek nokta; "
                        "daire = merkez etrafında tur")
    a.add_argument("--uzaklik", type=float, default=250.0,
                   help="hedefin bizden uzaklığı (m)")
    a.add_argument("--kerteriz", type=float, default=90.0,
                   help="(sabit desende) kuzeyden saat yönünde derece; "
                        "0=kuzey, 90=doğu")
    a.add_argument("--degisim", type=float, default=45.0,
                   help="(rastgele desende) kaç saniyede bir ışınlansın")
    a.add_argument("--tohum", type=int, default=1,
                   help="rastgeleliğin tohumu — aynı tohum aynı senaryo")
    a.add_argument("--takim", type=int, default=1,
                   help="hedef İHA'nın takım numarası")
    a.add_argument("--irtifa", type=float, default=80.0)
    a.add_argument("--yaricap", type=float, default=200.0)
    a.add_argument("--hiz", type=float, default=15.0)
    a.add_argument("--gurultu", type=float, default=3.0, help="metre (sigma)")
    a.add_argument("--sicrama", type=float, default=25.0, help="kaç sn'de bir")
    a.add_argument("--sicrama-m", type=float, default=40.0)
    a.add_argument("--kesinti", type=float, default=40.0, help="kaç sn'de bir")
    a.add_argument("--kesinti-sure", type=float, default=3.0)
    a.add_argument("--gecikme", type=float, default=1.0, help="saniye")
    a.add_argument("--gurultusuz", action="store_true",
                   help="hiç bozma — saf geometri sınaması")
    a = a.parse_args()

    Sunucu.hedef_takim = a.takim
    Sunucu.hedef = Hedef(desen=a.desen, irtifa=a.irtifa, uzaklik=a.uzaklik,
                         kerteriz=a.kerteriz, hiz=a.hiz, degisim=a.degisim,
                         yaricap=a.yaricap, tohum=a.tohum)
    if a.merkez != "oto":
        e0, b0 = (float(x) for x in a.merkez.split(","))
        Sunucu.hedef.merkez_kur(e0, b0)
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
    if a.merkez == "oto":
        print("  MERKEZ     : OTO — avcı dronun bildireceği ilk GEÇERLİ")
        print("               konum referans olacak. (0,0) gelirse hedef")
        print("               ÜRETİLMEZ, 'merkez bekleniyor' sayılır.")
    else:
        print("  MERKEZ     : %s (elle verildi)" % a.merkez)
    if a.desen == "rastgele":
        print("  HEDEF      : RASTGELE — her %g s'de bir yeni kerterize"
              % a.degisim)
        print("               ışınlanır, %g-%g m uzaklıkta doğar,"
              % (a.uzaklik * 0.6, a.uzaklik * 1.4))
        print("               dönem boyunca %g m/s ile düz uçar." % a.hiz)
        print("               ⭐ SORU: ışınlanınca avcı burnunu yeni")
        print("                  kerterize çeviriyor mu?")
    elif a.desen == "sabit":
        print("  HEDEF      : SABİT — kerteriz %g°, uzaklık %g m"
              % (a.kerteriz, a.uzaklik))
    else:
        print("  HEDEF      : DAİRE — %g m yarıçap, %g m/s (tur %.0f s)"
              % (a.yaricap, a.hiz, 2 * math.pi * a.yaricap / a.hiz))
    print("               irtifa %g m" % a.irtifa)
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
            nd = Sunucu.hedef.nerede()
            yer = ("merkez BEKLENİYOR (%d paket (0,0) geldi)"
                   % c["merkez_bekle"]) if not Sunucu.hedef.hazir else (
                  "hedef: kerteriz %.0f° · %.0f m" % nd if nd else "hedef: daire")
            print("  [%5.0f s] giriş %d · telemetri %d · red(biçim %d, hız %d)"
                  " · kilit %d  |  %s"
                  % (time.time() - Sunucu.bozucu.t0, c["giris"], c["telemetri"],
                     c["red_bicim"], c["red_hiz"], c["kilit"], yer))
    threading.Thread(target=rapor, daemon=True).start()
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        print("\n  kapatıldı. Toplam: %s" % Sunucu.sayac)


if __name__ == "__main__":
    main()
