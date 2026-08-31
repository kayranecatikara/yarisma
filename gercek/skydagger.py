# -*- coding: utf-8 -*-
"""
================================================================================
SKYDAGGER BAĞI — yarışma komitesinin RESMÎ PC↔ELRS yolu
================================================================================
Kaynak: "SKYDAGGER · PC-Güdümlü ELRS Handset Sistemi — Rehber v2.0"

    [bizim yazılım] --RC_US--> [backend] --USB seri--> [ESP32] --tek tel-->
    [ELRS 2.4G TX] --RF--> [alıcı] --> [F405]
           telemetri aynı yoldan GERİ akar (CRSF_JSON)

⭐ NİYE BU DOSYA VAR: komite, CRSF çerçevelemesini KENDİ backend'inde yapıyor.
   Biz ham CRSF baytı yazmıyoruz; METİN satırı yazıyoruz. Bu, `gercek/crsf.py`
   ile aynı işi FARKLI bir taşımayla yapmaktır — o yüzden bu sınıf `ElrsBag`
   ile AYNI ARAYÜZÜ sunar ve onun yerine geçer.
   ⛔ ÜST KATMANLAR (hakem, güdüm, panel, bağlantı) TEK SATIR DEĞİŞMEZ.

--------------------------------------------------------------------------------
PROTOKOL (rehber §8, §12)
--------------------------------------------------------------------------------
  RC (yukarı)      : "RC_US c1,c2,...,c16\\n"   tam 16 tamsayı, µs 988..2012
                     UDP 127.0.0.1:8767  (önerilen — en düşük gecikme)
                     TCP 127.0.0.1:8766  (garantili teslim)
  TELEMETRİ (aşağı): "CRSF_JSON {...}\\n"       TCP 127.0.0.1:8766
                     ⛔ AYRI İŞ PARÇACIĞINDA okunur; RC basmayı ASLA engellemez.

  KANALLAR (rehber §8, §10.3)
      CH1 Roll · CH2 Pitch · CH3 Throttle · CH4 Yaw
      CH5 ARM  : 988 = disarm, 2011 = arm
      CH6-16   : 988

  ⛔ SÜREKLİ BASMA KURALI: en az 5 Hz, önerilen 20-50 Hz. ESP son geçerli
     çerçeveyi ~200 ms tutar; o süre içinde yeni çerçeve gelmezse basmayı
     BIRAKIR ve link düşer.
     ⭐ Bu, bizim "kaynak yoksa PAKET KES" tasarımımızla BİREBİR uyuşuyor:
       kesme -> 200 ms sonra link düşer -> Betaflight AUTO-LAND. Rehber §11
       de aynı yolu tarif ediyor ("linki bırakır → dron kendi failsafe'ine").

--------------------------------------------------------------------------------
⛔ GÜVENLİ BAŞLANGIÇ — REHBERİN AÇIK KURALI (§8)
--------------------------------------------------------------------------------
"Kontrol/algoritma verisini HEMEN BASMAYIN. Script açılışta önce belirli bir
süre SAFE veri basmalı (CH5=988 disarm, CH3=988 gaz sıfır); bu sırada modülün
MAVİ ışığını doğrulayın."
Bu sınıf o pencereyi KENDİ uygular: `ac()` sonrası `GUVENLI_SURE_S` boyunca
ne gönderilirse gönderilsin SAFE basılır. Süre dolmadan kontrol verisi
GEÇMEZ ve bu durum `guvenli_pencere` ile dışarı bildirilir.

--------------------------------------------------------------------------------
BİRİM DÖNÜŞÜMLERİ — telemetri bize FARKLI birimlerde geliyor
--------------------------------------------------------------------------------
    Skydagger              ->  bizim iç sözleşmemiz (gercek/arayuz.py)
    gps.speed   km/h       ->  yer_hizi_ms  = km/h / 3.6
    gps.heading derece     ->  rota_deg     (aynı)
    gps.altitude m         ->  irtifa_amsl_m (aynı)
    attitude.*  DERECE     ->  *_rad        RADYAN'a çevrilir
    vario.vspeed m/s       ->  dusey_hiz_ms (aynı)
⛔ Dönüşüm YALNIZ burada yapılır (arayuz.py'nin birim kuralı).

⚠ `attitude.yaw` REHBERE GÖRE "GPS yoksa heading"tir. Yani bazı hâllerde
  BURUN değil ROTA olabilir. Hız vektörü zaten `gps.heading`ten (rota)
  hesaplanıyor; gövde dönüşümü ise yaw'ı kullanıyor. Rüzgârda ikisi
  ayrışır (bkz. konum.yer_hizindan_vektor). Bu, ÖLÇÜLMESİ gereken bir
  belirsizliktir — pusula (QMC5883) takılı olduğu için yaw'ın gerçek
  burun olması BEKLENİR, ama doğrulanmalıdır.
================================================================================
"""
import json
import math
import os
import socket
import threading
import time

US_MIN, US_ORTA, US_MAX = 988, 1500, 2012
ARM_US, DISARM_US = 2011, 988

#: Rehber §8'deki SAFE çerçevesi — birebir aynı.
SAFE = [US_ORTA, US_ORTA, US_MIN, US_ORTA, US_MIN, US_MIN, US_ORTA, US_MIN,
        US_MIN, US_MIN, US_MIN, US_MIN, US_ORTA, US_MIN, US_MIN, US_MIN]


class SkydaggerCfg:
    HOST      = os.environ.get("DOW_SKY_HOST", "127.0.0.1")
    UDP_PORT  = int(os.environ.get("DOW_SKY_UDP", 8767))
    TCP_PORT  = int(os.environ.get("DOW_SKY_TCP", 8766))
    #: "udp" = RC hızlı yol (rehberin önerisi), "tcp" = tek soket
    TASIMA    = os.environ.get("DOW_SKY_TASIMA", "udp").strip().lower()
    #: ⛔ Rehber §8: açılışta bu süre boyunca YALNIZ SAFE basılır.
    GUVENLI_SURE_S = float(os.environ.get("DOW_SKY_GUVENLI", 5.0))
    #: Telemetri bu süre gelmezse bağ ölü sayılır (üst katman da bakar).
    TELEM_ASIM_S = float(os.environ.get("DOW_SKY_TELEM_ASIM", 2.0))


def _kirp_us(x):
    x = int(round(x))
    return US_MIN if x < US_MIN else (US_MAX if x > US_MAX else x)


def cubuk_us(x):
    """Çubuk [-1,+1] -> µs. ⛔ Orta 1500; iki yarı KENDİ genişliğiyle ölçeklenir."""
    x = -1.0 if x < -1.0 else (1.0 if x > 1.0 else float(x))
    if x >= 0.0:
        return _kirp_us(US_ORTA + x * (US_MAX - US_ORTA))
    return _kirp_us(US_ORTA + x * (US_ORTA - US_MIN))


def us_cubuk(us):
    us = float(us)
    if us >= US_ORTA:
        return (us - US_ORTA) / float(US_MAX - US_ORTA)
    return (us - US_ORTA) / float(US_ORTA - US_MIN)


class _Sayac:
    """`ElrsBag.cozucu` ile aynı alanları sunar (panel/sağlık okuyor)."""
    def __init__(self):
        self.n_cerceve = 0
        self.n_crc_hata = 0      # ⛔ backend CRC'yi kendi yapıyor; daima 0
        self.n_atilan_bayt = 0


class SkydaggerBag:
    """`ElrsBag`in YERİNE GEÇER. Aynı metotlar, farklı taşıma.

    KULLANIM (drone_yki.py'de tek satır):
        bag = SkydaggerBag()          # ElrsBag(port=...) yerine
        bag.ac()
    """

    def __init__(self, cfg=SkydaggerCfg):
        self.cfg = cfg
        self.acik = False
        self.hata = None
        self.cozucu = _Sayac()
        self._udp = None
        self._tcp = None
        self._telem = {}
        self._telem_t = {}
        self._kilit = threading.Lock()
        self._is = None
        self._calisiyor = False
        self._acilis_t = 0.0
        # §5.1 mekanizma sütunları
        self.n_yazilan = 0
        self.n_yazma_hatasi = 0
        self.n_telem_satir = 0
        self.n_safe_basildi = 0
        self.son_satir = ""

    # ------------------------------------------------------------------
    @property
    def guvenli_pencere(self):
        """Açılıştan sonraki SAFE penceresi hâlâ sürüyor mu? (rehber §8)"""
        if not self.acik or self.cfg.GUVENLI_SURE_S <= 0:
            return False
        return (time.monotonic() - self._acilis_t) < self.cfg.GUVENLI_SURE_S

    def guvenli_kalan(self):
        if not self.guvenli_pencere:
            return 0.0
        return round(self.cfg.GUVENLI_SURE_S
                     - (time.monotonic() - self._acilis_t), 1)

    # ------------------------------------------------------------------
    def ac(self):
        c = self.cfg
        try:
            if c.TASIMA == "udp":
                self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._udp.connect((c.HOST, c.UDP_PORT))
            # Telemetri DAİMA TCP'den okunur (rehber §8.2 önerisi).
            self._tcp = socket.create_connection((c.HOST, c.TCP_PORT),
                                                 timeout=3.0)
            self._tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._tcp.settimeout(0.5)
        except Exception as e:
            self.hata = ("Skydagger backend'e bağlanılamadı (%s:%d) — %s: %s\n"
                         "   · backend çalışıyor mu?\n"
                         "   · konsolda /connect yapıldı mı?\n"
                         "   · EXTERNAL moduna geçildi mi?"
                         % (c.HOST, c.TCP_PORT, type(e).__name__, e))
            return False
        self.acik = True
        self._acilis_t = time.monotonic()
        self._calisiyor = True
        self._is = threading.Thread(target=self._telem_dongusu, daemon=True,
                                    name="skydagger-telem")
        self._is.start()
        return True

    def kapat(self):
        """⛔ DISARM GÖNDERMEZ. Rehber §11: backend kapanışı linki bırakır ve
        dron kendi failsafe'ine gider. Havadaki bir araca disarm göndermek
        onu DÜŞÜRÜR; doğru davranış basmayı bırakmaktır."""
        self._calisiyor = False
        self.acik = False
        for s in (self._udp, self._tcp):
            try:
                if s:
                    s.close()
            except Exception:
                pass

    # ---------------- RC yazma ----------------
    def kanal_yaz(self, kanallar):
        """16 µs değerini gönder. Döner: başarılı mı."""
        if not self.acik:
            return False
        if len(kanallar) != 16:
            self.n_yazma_hatasi += 1
            return False
        satir = "RC_US " + ",".join(str(_kirp_us(v)) for v in kanallar) + "\n"
        self.son_satir = satir.strip()
        try:
            if self.cfg.TASIMA == "udp":
                self._udp.send(satir.encode("ascii"))
            else:
                self._tcp.sendall(satir.encode("ascii"))
        except Exception as e:
            self.n_yazma_hatasi += 1
            self.hata = "yazma: %s" % e
            return False
        self.n_yazilan += 1
        self.cozucu.n_cerceve += 1
        return True

    def rc_gonder(self, throttle, pitch, roll, yaw, arm, harita=None, aux=None):
        """`ElrsBag.rc_gonder` ile AYNI imza — hakem hiçbir şey bilmez.

        ⛔ GÜVENLİ PENCERE: açılıştan sonraki ilk saniyelerde ne verilirse
           verilsin SAFE basılır (rehber §8). Böylece dron ilk komutu asla
           beklenmedik/agresif almaz.
        """
        if self.guvenli_pencere:
            self.n_safe_basildi += 1
            return self.kanal_yaz(SAFE)
        k = list(SAFE)
        k[0] = cubuk_us(roll)
        k[1] = cubuk_us(pitch)
        k[2] = cubuk_us(throttle)
        k[3] = cubuk_us(yaw)
        k[4] = ARM_US if arm else DISARM_US
        for kanal_no, deger in (aux or {}).items():
            i = int(kanal_no) - 1
            if 0 <= i < 16:
                k[i] = cubuk_us(deger)
        return self.kanal_yaz(k)

    def yaz(self, ham):
        """`ElrsBag.yaz` uyumluluğu — Skydagger ham CRSF kabul etmez."""
        raise NotImplementedError(
            "Skydagger METİN protokolü kullanır; ham CRSF yazılmaz. "
            "rc_gonder() ya da kanal_yaz() kullanın.")

    # ---------------- telemetri ----------------
    def _telem_dongusu(self):
        tampon = b""
        while self._calisiyor:
            try:
                veri = self._tcp.recv(8192)
            except socket.timeout:
                continue
            except Exception:
                break
            if not veri:
                break
            tampon += veri
            while b"\n" in tampon:
                satir, tampon = tampon.split(b"\n", 1)
                self._satir_isle(satir.decode("utf-8", "replace").strip())
            if len(tampon) > 65536:      # senkron kaybına karşı
                tampon = b""

    def _satir_isle(self, s):
        if not s.startswith("CRSF_JSON"):
            return
        try:
            m = json.loads(s[len("CRSF_JSON"):].strip())
        except Exception:
            return
        self.n_telem_satir += 1
        ad = m.get("name")
        simdi = time.monotonic()
        with self._kilit:
            if m.get("kind") == "telem" and ad:
                self._telem[ad] = m
                self._telem_t[ad] = simdi
            elif m.get("kind") == "telemetry":
                self._telem["link"] = m
                self._telem_t["link"] = simdi

    def oku(self, en_fazla=0):
        """`ElrsBag.oku` ile AYNI çıktı biçimi — BİZİM birimlerimizde.

        ⛔ Dönüşümler burada, tek yerde (arayuz.py birim kuralı):
             km/h -> m/s   ·   derece -> radyan
        """
        with self._kilit:
            t = dict(self._telem)
            zaman = dict(self._telem_t)
        if not t:
            return {}
        d = {}
        g = t.get("gps")
        if g is not None:
            try:
                d["gps"] = {
                    "enlem": float(g["lat"]), "boylam": float(g["lon"]),
                    # rehber: speed km/h  ->  m/s
                    "yer_hizi_ms": float(g.get("speed", 0.0)) / 3.6,
                    "rota_deg": float(g.get("heading", 0.0)),
                    "irtifa_amsl_m": float(g.get("altitude", 0.0)),
                    "uydu": int(g.get("sats", 0))}
            except (KeyError, TypeError, ValueError):
                pass
        a = t.get("attitude")
        if a is not None:
            try:
                # ⛔ REHBER DERECE VERİYOR — güdüm RADYAN bekler.
                d["durus"] = {"roll_rad": math.radians(float(a["roll"])),
                              "pitch_rad": math.radians(float(a["pitch"])),
                              "yaw_rad": math.radians(float(a["yaw"]))}
            except (KeyError, TypeError, ValueError):
                pass
        v = t.get("vario") or t.get("baro")
        if v is not None and "vspeed" in v:
            try:
                d["vario"] = {"dusey_hiz_ms": float(v["vspeed"])}
            except (TypeError, ValueError):
                pass
        L = t.get("link")
        if L is not None:
            d["link"] = {"yukari_lq": L.get("lq", L.get("uplink_lq", -1)),
                         "yukari_rssi_dbm": L.get("rssi", L.get("uplink_rssi", 0)),
                         "yukari_snr": L.get("snr", 0)}
        b = t.get("battery")
        if b is not None:
            d["pil"] = {"gerilim_v": b.get("voltage"), "akim_a": b.get("current"),
                        "pil_yuzde": b.get("remaining")}
        return d

    def durum(self):
        with self._kilit:
            zaman = dict(self._telem_t)
        simdi = time.monotonic()
        return {"acik": self.acik, "tasima": self.cfg.TASIMA,
                "guvenli_pencere": self.guvenli_pencere,
                "guvenli_kalan": self.guvenli_kalan(),
                "yazilan": self.n_yazilan, "yazma_hatasi": self.n_yazma_hatasi,
                "telem_satir": self.n_telem_satir,
                "safe_basildi": self.n_safe_basildi,
                "alanlar": {a: round(simdi - t, 2) for a, t in zaman.items()},
                "hata": self.hata}
