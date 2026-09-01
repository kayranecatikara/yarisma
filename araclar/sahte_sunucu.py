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
      "elle"     : ⭐ HEDEFİ SEN SÜRÜKLERSİN. `/harita` sayfasında hedefi
                   fareyle gezdirirsin; güdümün ürettiği yaw/pitch/roll
                   komutu ANINDA yanında görünür. Pervanesiz yer testi
                   için: "drone hedefe doğru komut üretiyor mu?"
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
        #: "elle" deseni: [kuzey_m, dogu_m] — /api/elle ile yazılır
        self.elle = [200.0, 0.0]
        self.elle_hiz = 0.0

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
        if self.desen == "elle":
            import math as _m
            return ((_m.degrees(_m.atan2(self.elle[1], self.elle[0])) + 360) % 360,
                    _m.hypot(self.elle[0], self.elle[1]))
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
        elif self.desen == "elle":
            # ⛔ SÜRÜKLENEN NOKTA. Hız, sürükleme hızından hesaplanır ki
            #   güdümün hedef-hız kestirimi (ileri besleme) anlamlı olsun.
            x, y = self.elle[0], self.elle[1]
            hiz = self.elle_hiz
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
    #: en küçük paket aralığı (s). 0.5 = 2 Hz = YARIŞMANIN GERÇEK SINIRI.
    hiz_siniri = 0.5
    #: bize gelen SON telemetri (harita sayfası aracın yerini bundan bilir)
    son_telem = {}
    #: GCS panelinden yansıtılan durum (arka planda 5 Hz çekilir)
    panel_durum = {}
    panel_adres = "http://127.0.0.1:8810"
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
        if self.path in ("/", "/harita"):
            ham = HARITA.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(ham)))
            self.end_headers()
            self.wfile.write(ham)
            return
        if self.path == "/api/harita":
            h = Sunucu.hedef
            t = Sunucu.son_telem or {}
            d = {"hazir": h.hazir, "desen": h.desen,
                 "hedef": {"kuzey": h.elle[0], "dogu": h.elle[1],
                           "irtifa": h.irtifa},
                 "panel": Sunucu.panel_durum}
            # aracın YEREL konumu: bize bildirdiği GPS - merkez
            if h.hazir and t.get("iha_enlem"):
                try:
                    dk = math.radians(float(t["iha_enlem"]) - h.e0) * h.M
                    dd = (math.radians(float(t["iha_boylam"]) - h.b0)
                          * h.N * h.cos0)
                    d["arac"] = {"kuzey": dk, "dogu": dd,
                                 "yaw": float(t.get("iha_yonelme") or 0.0),
                                 "irtifa": float(t.get("iha_irtifa") or 0.0)}
                except (TypeError, ValueError):
                    pass
            return self._yaz(200, d)
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
            if aralik < Sunucu.hiz_siniri:
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
            Sunucu.son_telem = g
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

        if self.path == "/api/elle":
            # ⛔ Hedefi HARİTADAN sürüklemek. Hız, iki sürükleme arasındaki
            #   yer değiştirmeden hesaplanır — güdümün ileri beslemesi
            #   (hedef hızı) anlamlı bir sayı görsün diye.
            h = Sunucu.hedef
            try:
                k = float(g.get("kuzey", h.elle[0]))
                dg = float(g.get("dogu", h.elle[1]))
            except (TypeError, ValueError):
                return self._yaz(400)
            simdi = time.monotonic()
            onceki = getattr(h, "_elle_t", None)
            if onceki is not None:
                dt = max(simdi - onceki, 1e-3)
                h.elle_hiz = min(80.0, math.hypot(k - h.elle[0],
                                                  dg - h.elle[1]) / dt)
            h._elle_t = simdi
            h.elle[0], h.elle[1] = k, dg
            # ⭐ Z EKSENİ: irtifa kaydırıcısından (kullanıcı isteği).
            #   Hedefin irtifası dikey güdümü sürer: istasyon noktası
            #   hedefin 6 m altında kurulur (MENZIL 8 × ALT_ORAN 0.75).
            if "irtifa" in g:
                try:
                    h.irtifa = max(0.0, min(300.0, float(g["irtifa"])))
                except (TypeError, ValueError):
                    pass
            return self._yaz(200, {"ok": True})

        if self.path == "/api/kilitlenme_bilgisi":
            Sunucu.sayac["kilit"] += 1
            return self._yaz(200, {"ok": True})

        self._yaz(404)


# ============================================================================
#  HARİTA SAYFASI — hedefi SÜRÜKLE, güdümün ürettiği komutu ANINDA gör
# ============================================================================
# ⛔ NİYE VAR (kullanıcı isteği 2026-09-02): pervaneler alındı, uçuş yasak.
#   Yerde kanıtlanabilecek en değerli şey şu: "hedef şurada olsa, drone
#   oraya doğru mu komut üretir?" Bu sayfa hedefi fareyle gezdirtir ve
#   güdümün O ANDA ürettiği yaw/pitch/roll komutunu dünya çerçevesine
#   çevirip hedefin kerteriziyle YAN YANA koyar.
#
# ⛔ TAM YARIŞMA YOLU KULLANILIR: hedef, gerçek sunucu şemasıyla
#   /api/telemetri_gonder yanıtında gider; GCS onu normal yoldan alır.
#   Değişen tek şey hedefin NEREDEN geldiğidir.
HARITA = r"""<!doctype html><meta charset=utf-8>
<title>Hedef Sürükle — güdüm ne komut veriyor?</title>
<style>
 body{background:#0e1116;color:#dbe3ee;font:13px/1.5 system-ui,sans-serif;
      margin:0;display:flex;gap:14px;padding:14px}
 canvas{background:#141a22;border:1px solid #2a3441;border-radius:8px;
        cursor:crosshair}
 .yan{min-width:330px}
 h1{font-size:15px;margin:0 0 10px;color:#9fb4cc;font-weight:600}
 .kutu{background:#141a22;border:1px solid #2a3441;border-radius:8px;
       padding:10px 12px;margin-bottom:10px}
 .sat{display:flex;justify-content:space-between;padding:2px 0}
 .sat b{color:#9fb4cc;font-weight:500}
 .buyuk{font-size:30px;font-weight:700;text-align:center;padding:6px 0}
 .iyi{color:#4ade80}.orta{color:#fbbf24}.kotu{color:#f87171}
 .ipucu{color:#7c8ba1;font-size:12px;line-height:1.6}
 code{background:#1c2430;padding:1px 5px;border-radius:4px;color:#9fb4cc}
</style>
<canvas id=c width=660 height=660></canvas>
<div style="display:flex;flex-direction:column;align-items:center;gap:8px">
  <div style="color:#9fb4cc;font-size:12px">HEDEF<br>İRTİFA</div>
  <input id=irt type=range min=0 max=120 step=1 value=40
         style="writing-mode:vertical-lr;direction:rtl;height:520px;width:32px">
  <div id=irtv style="font-size:20px;font-weight:700;color:#fbbf24">40 m</div>
  <div id=irtd style="color:#7c8ba1;font-size:11px;text-align:center">
    araç<br>— m</div>
</div>
<div class=yan>
 <h1>Hedefi sürükle — komut nereyi gösteriyor?</h1>
 <div class=kutu>
   <div class=sat><b>gereken dönüş</b><span id=gd>—</span></div>
   <div class=sat><b>güdümün yaw komutu</b><span id=yk>—</span></div>
   <div class=buyuk id=fark>—</div>
   <div class=ipucu id=yorum>bekleniyor…</div>
 </div>
 <div class=kutu>
   <div class=sat><b>hedefin kerterizi</b><span id=hk>—</span></div>
   <div class=sat><b>komutun kerterizi</b><span id=kk>—</span></div>
   <div class=sat><b>fark (yön)</b><span id=yfark>—</span></div>
   <div class=ipucu id=doyum></div>
 </div>
 <div class=kutu>
   <div class=sat><b>kip (panel)</b><span id=kip>—</span></div>
   <div class=sat><b>kaynak</b><span id=kaynak>—</span></div>
   <div class=sat><b>⛔ sebep</b><span id=sebep>—</span></div>
   <div class=sat><b>güdüm</b><span id=gudum>—</span></div>
   <div class=sat><b>arm</b><span id=arm>—</span></div>
   <div class=sat><b>burun (yaw)</b><span id=yaw>—</span></div>
   <div class=sat><b>uzaklık</b><span id=uz>—</span></div>
 </div>
 <div class=kutu>
   <div class=sat><b>çubuk pitch (ileri)</b><span id=cp>—</span></div>
   <div class=sat><b>çubuk roll (sağ)</b><span id=cr>—</span></div>
   <div class=sat><b>çubuk yaw</b><span id=cy>—</span></div>
   <div class=sat><b>çubuk throttle</b><span id=ct>—</span></div>
 </div>
 <div class=kutu ipucu>
   <div class=ipucu>
   <b>⛔ YERDE ASIL ÖLÇÜT: DÖNÜŞ YÖNÜ.</b> Güdüm "burnunu çevir, sonra
   düz git" stratejisi kullanır. Yerdeki araç DÖNEMEZ ve hız hatası hep
   azami olduğu için <code>pitch</code> daima +1.00'de DOYAR — o yüzden
   yeşil ok yerde aracın BURNUNU gösterir, hedefi değil. Bu normaldir.<br><br>
   <b>Bakılacak şey:</b> hedefi sağa koyunca yaw komutu <b>+</b>, sola
   koyunca <b>−</b> olmalı ve büyüklüğü açıyla artmalı. Büyük yazı bunu
   söyler.<br><br>
   <b>Ok da doğrulanabilir:</b> aracı elinde çevirip burnunu hedefe
   doğrult — o zaman doyum sorun olmaz, yeşil ok sarı çizgiyle
   ÇAKIŞMALIDIR.<br><br>
   ⛔ Araç DISARM ve pervanesiz olmalı.<br>
   ⛔ Panelde <code>KÖKEN KUR</code> → <code>OTONOM</code> basılı olmalı.
   </div>
 </div>
</div>
<script>
const c=document.getElementById("c"), x=c.getContext("2d");
const W=c.width, H=c.height, MERKEZ={x:W/2,y:H/2};
let OLCEK=0.55;            // piksel / metre
let D={}, surukle=false, sonPost=0;
function m2p(k,d){ return {x:MERKEZ.x+d*OLCEK, y:MERKEZ.y-k*OLCEK}; }
function p2m(px,py){ return {kuzey:(MERKEZ.y-py)/OLCEK, dogu:(px-MERKEZ.x)/OLCEK}; }
function sar(a){ return ((a+180)%360+360)%360-180; }

c.addEventListener("mousedown",e=>{surukle=true;tasi(e);});
addEventListener("mouseup",()=>surukle=false);
c.addEventListener("mousemove",e=>{ if(surukle) tasi(e); });
c.addEventListener("wheel",e=>{ e.preventDefault();
  OLCEK*=e.deltaY<0?1.15:0.87; OLCEK=Math.max(0.05,Math.min(6,OLCEK)); ciz(); });
function tasi(e){
  const r=c.getBoundingClientRect();
  const m=p2m(e.clientX-r.left, e.clientY-r.top);
  D.hedef=D.hedef||{}; D.hedef.kuzey=m.kuzey; D.hedef.dogu=m.dogu;
  ciz();
  const t=Date.now(); if(t-sonPost<80) return; sonPost=t;
  fetch("/api/elle",{method:"POST",
    body:JSON.stringify({kuzey:m.kuzey,dogu:m.dogu})}).catch(()=>{});
}
function ok(x0,y0,kert,uzun,renk,kalin){
  const r=(90-kert)*Math.PI/180;
  const x1=x0+Math.cos(r)*uzun, y1=y0-Math.sin(r)*uzun;
  x.strokeStyle=renk; x.fillStyle=renk; x.lineWidth=kalin;
  x.beginPath(); x.moveTo(x0,y0); x.lineTo(x1,y1); x.stroke();
  x.beginPath(); x.arc(x1,y1,kalin+2,0,7); x.fill();
}
function ciz(){
  x.clearRect(0,0,W,H);
  x.strokeStyle="#1f2937"; x.lineWidth=1;
  for(let m=-2000;m<=2000;m+=50){ const p=m2p(m,0), q=m2p(0,m);
    x.beginPath(); x.moveTo(0,p.y); x.lineTo(W,p.y); x.stroke();
    x.beginPath(); x.moveTo(q.x,0); x.lineTo(q.x,H); x.stroke(); }
  x.fillStyle="#7c8ba1"; x.font="12px system-ui";
  x.fillText("KUZEY ↑   ·   1 kare = 50 m   ·   tekerlek = yakınlaştır",10,18);
  const a=D.arac, h=D.hedef; if(!h) return;
  const ap = a? m2p(a.kuzey,a.dogu) : m2p(0,0);
  const hp = m2p(h.kuzey,h.dogu);
  // hedefe giden sarı çizgi
  x.strokeStyle="#fbbf24"; x.lineWidth=2; x.setLineDash([6,5]);
  x.beginPath(); x.moveTo(ap.x,ap.y); x.lineTo(hp.x,hp.y); x.stroke();
  x.setLineDash([]);
  // hedef
  x.fillStyle="#fbbf24"; x.beginPath(); x.arc(hp.x,hp.y,9,0,7); x.fill();
  x.fillStyle="#0e1116"; x.font="bold 11px system-ui";
  x.fillText("H",hp.x-4,hp.y+4);
  // araç + burun
  if(a){
    ok(ap.x,ap.y,a.yaw,34,"#60a5fa",2);
    x.fillStyle="#60a5fa"; x.beginPath(); x.arc(ap.x,ap.y,7,0,7); x.fill();
  }
  // komut oku
  const oc=(D.panel||{}).oto_cubuk;
  if(a && oc && (Math.abs(oc.pitch)>0.02||Math.abs(oc.roll)>0.02)){
    const y=a.yaw*Math.PI/180;
    const kn=oc.pitch*Math.cos(y)-oc.roll*Math.sin(y);
    const dg=oc.pitch*Math.sin(y)+oc.roll*Math.cos(y);
    const kert=(Math.atan2(dg,kn)*180/Math.PI+360)%360;
    ok(ap.x,ap.y,kert,120,"#4ade80",3);
  }
}
async function tik(){
  try{ D=await (await fetch("/api/harita")).json(); }catch(e){ }
  const a=D.arac, h=D.hedef, p=D.panel||{}, oc=p.oto_cubuk, du=p.durus||{};
  const g=(i,v)=>document.getElementById(i).textContent=v;
  const K=p.komut||{};
  g("kip",K.kip||"—");
  g("kaynak",K.kaynak||"—");
  g("sebep",K.sebep&&K.sebep!="-"?K.sebep:"—");
  const G=p.gudum||{};
  g("gudum",(G.durum||"—")+((G.tik&&G.tik!=G.durum)?("  ⛔ "+G.tik):""));
  g("arm",(p.komut||{}).arm===true?"ARM":"disarm");
  g("yaw",a?a.yaw.toFixed(1)+"°":"—");
  document.getElementById("irtd").innerHTML =
    "araç<br>"+(a?a.irtifa.toFixed(0):"—")+" m";
  if(D.hedef && !sIrt.matches(":active") && D.hedef.irtifa!=null
     && Math.abs(D.hedef.irtifa-parseFloat(sIrt.value))>0.6){
    sIrt.value=D.hedef.irtifa;
    document.getElementById("irtv").textContent=sIrt.value+" m";
  }
  g("cp",oc?oc.pitch.toFixed(3):"—"); g("cr",oc?oc.roll.toFixed(3):"—");
  g("cy",oc?oc.yaw.toFixed(3):"—");   g("ct",oc?oc.throttle.toFixed(3):"—");
  if(a&&h){
    const bk=h.kuzey-a.kuzey, bd=h.dogu-a.dogu;
    const hk=(Math.atan2(bd,bk)*180/Math.PI+360)%360;
    g("hk",hk.toFixed(0)+"°");
    g("uz",Math.hypot(bk,bd).toFixed(0)+" m");
    const e=document.getElementById("fark");
    if(oc){
      // ⭐ BIRINCIL OLCUT: donus yonu. Yerde arac donemez, ama gudumun
      //   HANGI YONE cevirmek istedigi olculebilir.
      const ger=sar(hk-a.yaw);                 // + = saga donmeli
      g("gd",(ger>0?"+":"")+ger.toFixed(0)+"°  ("+(ger>0?"SAĞA":"SOLA")+")");
      g("yk",(oc.yaw>0?"+":"")+oc.yaw.toFixed(3)+
             (Math.abs(oc.yaw)<0.02?"  (yok)":"  ("+(oc.yaw>0?"sağa":"sola")+")"));
      // ⛔ EŞİKLER ÖLÇÜLDÜ (2026-09-02, yumuşak sürükleme, 75 örnek):
      //   güdüm burnu hedefin ±10°'sinde tutuyor; bu bantta yaw komutu
      //   ±0.06 mertebesinde titriyor ve İŞARETİ ANLAMSIZ. O yüzden
      //   "TERS" hükmü YALNIZ belirgin bir açı hatası VE belirgin bir
      //   komut varken kurulur — yoksa sayfa boşuna alarm verir.
      if(Math.abs(ger)<12){
        e.textContent="BURUN HEDEFTE"; e.className="buyuk iyi";
        document.getElementById("yorum").innerHTML=
          "burun zaten hedefe dönük — dönüş komutu beklenmez. Hedefi "+
          "yana sürükleyip yaw komutunun işaretine bak.";
      } else if(Math.abs(oc.yaw)<0.08){
        e.textContent="DÖNÜŞ ZAYIF"; e.className="buyuk orta";
        document.getElementById("yorum").innerHTML=
          "hedef "+Math.abs(ger).toFixed(0)+"° "+(ger>0?"sağda":"solda")+
          " ama yaw komutu küçük ("+oc.yaw.toFixed(3)+"). Hedefi biraz "+
          "daha yana götür; komut açıyla büyümeli.";
      } else if(Math.sign(oc.yaw)===Math.sign(ger)){
        e.textContent="✔ DOĞRU YÖN"; e.className="buyuk iyi";
        document.getElementById("yorum").innerHTML=
          "hedef "+Math.abs(ger).toFixed(0)+"° "+(ger>0?"sağda":"solda")+
          ", güdüm de "+(oc.yaw>0?"sağa":"sola")+" dönüyor.";
      } else {
        e.textContent="⛔ TERS YÖN"; e.className="buyuk kotu";
        document.getElementById("yorum").innerHTML=
          "⛔⛔ hedef "+(ger>0?"SAĞDA":"SOLDA")+" ama güdüm "+
          (oc.yaw>0?"SAĞA":"SOLA")+" dönüyor. İşaret hatası — "+
          "<code>yon_testi.py --mod cevir</code> koş.";
      }
      // ikincil: dunya yonu (yerde DOYUM yuzunden yaniltici olabilir)
      const y=a.yaw*Math.PI/180;
      const kn=oc.pitch*Math.cos(y)-oc.roll*Math.sin(y);
      const dg=oc.pitch*Math.sin(y)+oc.roll*Math.cos(y);
      const kk=(Math.atan2(dg,kn)*180/Math.PI+360)%360;
      g("kk",kk.toFixed(0)+"°");
      const f=sar(kk-hk);
      g("yfark",(f>0?"+":"")+f.toFixed(0)+"°");
      const doy=Math.abs(oc.pitch)>0.98||Math.abs(oc.roll)>0.98;
      document.getElementById("doyum").innerHTML= doy
        ? "⚠ çubuk DOYUMDA (pitch/roll ±1.00) — yerde normaldir. Bu "+
          "haldeyken ok aracın BURNUNU gösterir, hedefi değil."
        : (Math.abs(f)<20 ? "✔ ok hedefe çakışıyor" : "");
    } else {
      g("kk","—"); g("gd","—"); g("yk","—"); g("yfark","—");
      e.textContent="—"; e.className="buyuk";
      // ⛔ TEŞHİS: hakemin `sebep` alanı hangi şartın düştüğünü SÖYLER.
      //   Genel bir "KÖKEN KUR + OTONOM gerekli" metni operatörü kör
      //   bırakıyordu (2026-09-02'de sahada yaşandı).
      const S1={
        "gudum_bayat":"güdüm taze setpoint ÜRETMİYOR. En sık sebebi "+
          "KÖKENİN KURULMAMASI (panelde <code>güdüm</code> alanı "+
          "<code>KOKEN_YOK</code> yazar). Telemetri de ölmüş olabilir "+
          "(<code>BAGLANTI_YOK</code>).",
        "pilot_vetosu":"pilot izni YOK. Panel <code>izin</code> "+
          "göndermiyor — MANUEL'e basıp tekrar OTONOM'a bas.",
        "teslim_suresi":"3 saniyedir hiçbir insan girdisi yok "+
          "(panel sekmesi arka planda olabilir).",
        "paket_kesildi":"ne panel ne kumanda var — RC KESİLDİ."};
      const K2=p.komut||{};
      document.getElementById("yorum").innerHTML=
        p.hata ? ("panel okunamıyor: "+p.hata)
        : (K2.kip!=="OTONOM"
           ? "⛔ panel kipi <code>"+(K2.kip||"?")+"</code> — önce panelde "+
             "<b>OTONOM</b>'a bas."
           : (S1[K2.sebep] || ("kaynak="+(K2.kaynak||"?")+
                               " sebep="+(K2.sebep||"?"))));
    }
  }
  ciz();
}
const sIrt=document.getElementById("irt");
function irtGonder(){
  document.getElementById("irtv").textContent=sIrt.value+" m";
  const h=D.hedef||{};
  fetch("/api/elle",{method:"POST",body:JSON.stringify(
    {kuzey:h.kuzey||0, dogu:h.dogu||0, irtifa:parseFloat(sIrt.value)})})
    .catch(()=>{});
}
sIrt.addEventListener("input",irtGonder);
setInterval(tik,150); tik();
</script>
"""


def main():
    a = argparse.ArgumentParser(description="Sahte yarışma sunucusu")
    a.add_argument("--port", type=int, default=10001)
    a.add_argument("--panel", default="http://127.0.0.1:8810",
                   help="GCS paneli — harita sayfası komutları oradan yansıtır")
    a.add_argument("--merkez", default="oto",
                   help="referans nokta: 'oto' (VARSAYILAN — avcı dronun "
                        "kendi bildirdiği ilk konum) ya da enlem,boylam")
    a.add_argument("--desen", default="rastgele",
                   choices=("elle", "rastgele", "sabit", "daire"),
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
    a.add_argument("--hz-siniri", type=float, default=2.0,
                   help="⛔ istemcinin aşamayacağı Hz. VARSAYILAN 2.0 = "
                        "yarışmanın GERÇEK sınırı. Yükseltmek testi "
                        "yarışmadan FARKLI kılar")
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
    a.add_argument("--gecikme", type=float, default=None,
                   help="saniye. VARSAYILAN: 'elle' deseninde 0, "
                        "diğerlerinde 1.0")
    a.add_argument("--gurultusuz", action="store_true",
                   help="hiç bozma — saf geometri sınaması")
    a = a.parse_args()

    # ⛔⛔ `elle` DESENİNDE GECİKME 0 (2026-09-02, sahada yakalandı).
    #   `--gecikme` `zaman_farki` alanına yazılıyor ve `hedef.py`
    #   tazeliği `ulasma + zaman_farki` diye hesaplıyor. Varsayılan 1.0 s
    #   ile toplam yaş ~1.3 s oluyordu; eşik `MAX_YAS_S = 1.5`. Yani
    #   ufak bir aksama hedefi "BAYAT" yapıyor ve ön uçuş listesi
    #   kırmızıya dönüyordu.
    #   `elle` deseninde gecikmenin ANLAMI YOK: hedefin konumunu az önce
    #   SEN sürükledin, "1 saniye önceki hâli" diye bir şey yok.
    if a.gecikme is None:
        a.gecikme = 0.0 if a.desen == "elle" else 1.0
    Sunucu.hedef_takim = a.takim
    Sunucu.hiz_siniri = 1.0 / max(0.1, a.hz_siniri)
    Sunucu.panel_adres = a.panel
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
    if a.desen == "elle":
        print("  HEDEF      : ELLE — hedefi SEN sürükleyeceksin")
        print("               ⭐ HARİTA:  http://127.0.0.1:%d/harita" % a.port)
        print("               Panelde KÖKEN KUR + OTONOM basılı olmalı,")
        print("               yoksa güdüm komut üretmez ve ok görünmez.")
    elif a.desen == "rastgele":
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
    if a.hz_siniri > 2.0 + 1e-9:
        print("  ⚠⚠ HIZ SINIRI %.1f Hz'e YÜKSELTİLDİ — yarışma sınırı 2 Hz."
              % a.hz_siniri)
        print("     Bu koşu hedef tazeliği bakımından YARIŞMAYI TEMSİL ETMEZ.")
    else:
        print("  ⛔ Telemetri BİÇİMİ ve %g Hz sınırı GERÇEKTEN denetlenir."
              % a.hz_siniri)
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

    def panel_cek():
        """GCS panelini 5 Hz yansıt. ⛔ AYRI İŞ PARÇACIĞI: HTTP işleyicisi
        panelin yavaşlamasından ETKİLENMEMELİ."""
        import urllib.request
        while True:
            try:
                with urllib.request.urlopen(
                        Sunucu.panel_adres + "/api/durum", timeout=1.0) as c:
                    d = json.loads(c.read().decode())
                Sunucu.panel_durum = {
                    "oto_cubuk": d.get("oto_cubuk"), "durus": d.get("durus"),
                    "komut": {k: (d.get("komut") or {}).get(k)
                              for k in ("kaynak", "sebep", "arm", "kip")},
                    "gudum": d.get("gudum"), "konum": d.get("konum"),
                    "hedef": {"var": (d.get("hedef") or {}).get("var")}}
            except Exception as e:
                Sunucu.panel_durum = {"hata": str(e)[:80]}
            time.sleep(0.2)
    threading.Thread(target=panel_cek, daemon=True).start()
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        print("\n  kapatıldı. Toplam: %s" % Sunucu.sayac)


if __name__ == "__main__":
    main()
