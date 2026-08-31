# -*- coding: utf-8 -*-
"""
================================================================================
DoW PANELİ — WEB, YÜKSEK FPS, ANALİZ ODAKLI
================================================================================
Adres: http://127.0.0.1:8801  (normal tarayıcı sekmesi; MJPEG akışı)

TASARIM
  * Kaydırıcı YOK, ayar kutusu YOK. Ayarları yapay zekâ değiştirir.
  * Üç güdüm düğmesi: HİBRİT / GPS / GÖRSEL — uçuş sırasında canlı geçer.
  * Üç FPS sayacı (YAKALAMA / DEDEKTÖR / EKRAN) TAVANIYLA birlikte basılır ki
    sayı yanıltmasın: "12.0 / 30" = tavan 30, ulaşılan 12.
  * TESPİT ŞERİDİ: son ~20 s'nin kare kare tespit haritası.

⭐ HybridSORT TAKİPÇİSİ GERİ (2026-08-24, kullanıcı kararı):
   22 Ağustos'ta "detection kötü olduğu için tracking işe yaramıyor" diye
   çıkarılmıştı; koşul "düzgün detection modeli gelince geri gelir"di ve
   talon_v5 ile gerçekleşti. Panel yeniden iz kimliğini (ID), kutunun
   kaynağını (eşleşme/öngörü) ve coast sayısını gösterir.

⚡ MALİYET (ölçüldü 2026-08-22 — arayüz UÇUŞU BOZUYORDU):
   Eski sürümde ekran saniyede 180-330 kez kopyalanıyordu ve MJPEG yazıcısı
   4 ms'de bir boşuna uyanıyordu. Şimdi: yakalama tavanlı (Ayar.PANEL_YAKALA_HZ)
   ve MJPEG yazıcısı KOŞUL DEĞİŞKENİYLE uyutuluyor — yeni kare gelince uyanır,
   yoksa hiç CPU yemez.
================================================================================
"""
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from dow.ayarlar import Ayar     # kilit eşikleri buradan (TEK KAYNAK)

_K = {"jpg": None, "zoom": None, "telem": {}, "sayac": 0}
_kosul = threading.Condition()          # yeni kare bildirimi (boş bekleme YOK)
_serit = deque(maxlen=400)              # (t, durum) 0=tespit yok, 1=tespit

# ⭐ YARIŞMA KİLİT ÖLÇÜTÜ (2026-08-24) — BİZDE HİÇ YOKTU.
#   Panelde "kutu var mı" gösteriyorduk ama yarışmanın PUAN verdiği şey o değil:
#   hedefin kadrajın ORTA bölgesinde (AV dörtgeni) VE yeterince BÜYÜK görünmesi,
#   ve bunun 10 saniyelik pencerede toplam 5 saniye sürmesi.
#   ⚠ ÇİZİMİ ARAYÜZ YAPAR (dow/web/index.html); burada YALNIZ HESAPLANIR —
#     sunucu ikinci kez çizerse kutular üst üste biner.
#
# ⛔⛔ TEK KAYNAK (2026-08-28): eşikler ARTIK BURADA TANIMLANMIYOR.
#   Buradaki sayılar 2026-08-24'te "yer-kontrol deposunun şartname
#   okumasından" alınmıştı ve DOĞRULANMAMIŞTI. Şartname (Teknofest 6.1.4)
#   okununca ölçüt `dow/gudum/kilit.py`'ye yazıldı ve GÜDÜME bağlandı.
#   İki ayrı tanım bırakmak §5.12'nin uyardığı sürüklenmedir: panel bir
#   şey der, güdüm başka şey yapar. Bu yüzden panel artık AYNI modülü ve
#   AYNI `Ayar.KILIT_*` sabitlerini kullanır.
KILIT_PCT   = Ayar.KILIT_BOYUT_YUZDE / 100.0
KILIT_AV_X  = Ayar.KILIT_KIRP_X       # yatay %25-%75 bandı
KILIT_AV_Y  = Ayar.KILIT_KIRP_Y       # dikey %10-%90 bandı
KILIT_WIN_S = Ayar.KILIT_PENCERE_S    # değerlendirme penceresi
KILIT_GEREK = Ayar.KILIT_GEREKLI_S    # pencerede gereken kümülatif kilit
_kilit_pencere = deque(maxlen=1200)     # (t, kilitli_mi)
# Ölçütün TEK kaynağı; durum tutmadan yalnız `kare_kilitli` için kullanılır.
from dow.gudum.kilit import KilitDurumu as _KilitDurumu
_KILIT_OLCUT = _KilitDurumu(Ayar)

# ⭐ PANELDEN GÖREV BAŞLATMA (2026-08-25, kullanıcı isteği: "arayüzden göreve
#   başlata basınca en iyi hali çıksın").
#   Uçuş sürecini (`araclar/kosu.py`) panel BAŞLATMAZ — panel zaten O sürecin
#   içinde koşuyor. Onun yerine kosu.py, kapı AÇILANA KADAR bekler; düğme
#   bu bayrağı kaldırır. Böylece tek komutla başlatıp arayüzden tetikliyoruz.
_basla = threading.Event()


def baslat_bekle(zaman_asimi=None):
    """Uçuş döngüsü, panelden 'Görev Başlat' gelene kadar bekler."""
    return _basla.wait(zaman_asimi)


def baslat_istendi():
    return _basla.is_set()
_fps = {"yakala": deque(maxlen=40), "dedektor": deque(maxlen=40),
        "ekran": deque(maxlen=40)}
_TAVAN = {"yakala": 0.0, "dedektor": 0.0}


def _hz(d):
    if len(d) < 2:
        return 0.0
    dt = d[-1] - d[0]
    return (len(d) - 1) / dt if dt > 1e-6 else 0.0


def _api_telemetry():
    """⭐ YER-KONTROL ARAYÜZÜ UYARLAYICISI (2026-08-24, kullanıcı isteği).

    `dow/web/index.html` (kullanıcının attığı `model-fps` branch'inden AYNEN
    alındı) İÇ İÇE bir telemetri şeması bekliyor; bizim güdüm telemetrimiz DÜZ
    bir sözlük (`beyin.tani` + `kosu.py`'nin eklediği gösterim alanları).
    Bu fonksiyon düzü o şekle çevirir.

    ⛔ BİZDE OLMAYAN ALANLAR UYDURULMAZ. Onların sistemi PnP poz kestirimi,
    GNSS J-filtre kıyası ve olay günlüğü de yayınlıyor; bizde o modüller YOK.
    O alanlar boş/None bırakılır ve arayüz "—" gösterir. Sahte sayı, boş
    hücreden kötüdür.

    ⛔ §10 (YARIŞMA KISITI): buradaki hedef konumu/mesafesi YALNIZ EKRANA
    gider. Görsel güdüm (`Beyin._gorsel_tik_kilitli`) bu alanların hiçbirini
    görmez — girdisi yalnız görüntüdür. meta.csv'deki truth sütunlarıyla aynı
    statüdedir: ölçüm/gösterim kanalı.
    """
    with _kosul:
        t = dict(_K["telem"])
    from dow.ayarlar import kip_oku, Ayar
    from dow.gorus.tracker import TakipCfg

    def g(k, d=None):
        v = t.get(k, d)
        return d if v is None else v

    W = float(g("kare_w", 1920) or 1920)
    H = float(g("kare_h", 1080) or 1080)
    durum = str(g("durum", "-"))

    tespit = None
    cx, cy, bw = t.get("vis_cx"), t.get("vis_cy"), t.get("vis_w")
    if cx is not None and bw:
        bh = t.get("vis_h") or bw * 0.7
        kaynak = str(g("takip_kaynak", "") or "")
        tespit = {
            "ex": (cx - W / 2.0) / (W / 2.0),      # + = hedef SAĞDA
            "ey": (cy - H / 2.0) / (H / 2.0),      # + = hedef ALTTA
            "cx": cx / W, "cy": cy / H,
            "w": bw / W, "h": bh / H,
            "conf": float(g("vis_conf", 0.0) or 0.0),
            "cls": 0, "sinif": "talon",
            "track_id": (None if g("takip_id", -1) in (-1, None)
                         else int(g("takip_id"))),
            "track_durumu": ("CONFIRMED" if kaynak == "eslesme"
                             else ("COAST" if kaynak == "tahmin" else None)),
            # ⭐ tespit_mi=False -> arayüz kutuyu KESİKLİ çizer. Bizde bu,
            #   takipçinin Kalman ÖNGÖRÜSÜ demektir (o karede ÖLÇÜM YOK).
            "tespit_mi": (kaynak != "tahmin"),
        }

    serit, oran = _serit_ozet()
    kl_s = float(g("kilit_pencere_s", 0.0) or 0.0)
    gorsel = {
        "tespit": tespit,
        "durum": durum,
        "mod": kip_oku(),
        "perf": {"fps": round(_hz(_fps["dedektor"]), 1),
                 "det_ms": g("det_ms", 0.0),
                 "det_p95": None, "poz_ms": None, "gpu": None,
                 "yakala_fps": round(_hz(_fps["yakala"]), 1),
                 "ekran_fps": round(_hz(_fps["ekran"]), 1)},
        "conf_esik": (TakipCfg.CONF_MIN if TakipCfg.AKTIF else 0.40),
        "n_lock": g("kilit_kare", 0),
        "pos_count": g("kilit_kare", 0),
        "kare_kaynak": "panel MJPEG (mss)",
        "prop_maske": [],
        "poz": None, "poz_hazir": False,           # PnP bizde YOK
        "kopru": {"aktif": durum == "GORSEL_KOPRU", "kare": g("kopru_kare", 0)},
        # ⭐ İKİ AYRI KİLİT SAYISI VAR, KARIŞTIRILMAMALI:
        #   `sure`      : PANELİN kendi penceresi (yakalama hızında, gösterim)
        #   `gudum_s`   : GÜDÜMÜN muhasebesi (çıkarım hızında, KARAR bunu verir)
        #   Faz geçişini `gudum_s`/`saglandi` belirler; panelin sayısı
        #   operatöre gösterim içindir. Eşikleri aynı modülden okurlar.
        "kilit": {"anlik": bool(g("kilit_simdi", 0)),
                  "sure": kl_s, "gerek": KILIT_GEREK, "pencere": KILIT_WIN_S,
                  "ok": kl_s >= KILIT_GEREK, "esik_pct": KILIT_PCT,
                  "kaplama_pct": g("kilit_kaplama", 0.0),
                  "av": bool(g("kilit_av", 0)),
                  "faz_acik": bool(Ayar.KILIT_FAZI),
                  "faz": g("faz", "-"),
                  "gudum_s": g("kilit_s", 0.0),
                  "saglandi": bool(g("kilit_saglandi", 0)),
                  "sebep": g("kilit_sebep", "-")},
        "serit": serit, "ham_tespit_oran": oran,
    }

    takip = {"aktif": bool(TakipCfg.AKTIF),
             "id": (None if g("takip_id", -1) in (-1, None) else int(g("takip_id"))),
             "kayip": g("yerel_kayip", 0), "yeniden": None,
             "coast": g("takip_coast", -1), "iz_sayisi": g("takip_n", 0),
             "kaynak": g("takip_kaynak", "")}

    # ⭐ HEDEF KONUMU — 3B grafik için truth kanalına DÜŞ (2026-08-26).
    #   `h_*` yalnız GPS okunabildiğinde dolar; GORSEL fazda hp YOKTUR (§10)
    #   ve grafik orada DONARDI. `t_*` truth kanalıdır, her fazda dolu.
    #   ⛔ İkisi de YALNIZ EKRANA gider; görsel güdüm hiçbirini görmez.
    #   ⚠ Değişken adı `_hz` OLAMAZ: modül düzeyindeki `_hz()` fonksiyonunu
    #     gölgeler ve Python fonksiyonun TAMAMINDA onu yerel sayar ->
    #     yukarıdaki `_hz(_fps[...])` çağrıları UnboundLocalError atar ve
    #     /api/telemetry komple çöker. (2026-08-26'da tam bu yaşandı.)
    _hedx = t.get("h_x") if t.get("h_x") is not None else t.get("t_x")
    _hedy = t.get("h_y") if t.get("h_y") is not None else t.get("t_y")
    _hedz = t.get("h_z") if t.get("h_z") is not None else t.get("t_z")
    hedef = ({"x": _hedx, "y": _hedy, "z": _hedz,
              "speed_ms": None, "speed_kmh": None}
             if _hedx is not None else {})
    return {
        "connected": True,
        "drone": {"x": g("d_x", 0.0), "y": g("d_y", 0.0), "z": g("d_z", 0.0),
                  "altitude_m": g("yukseklik", 0.0),
                  "speed_ms": g("drone_hiz", 0.0),
                  "speed_kmh": (g("drone_hiz", 0.0) or 0.0) * 3.6,
                  "roll": g("d_roll", 0.0), "pitch": g("d_pitch", 0.0),
                  "yaw": g("d_yaw", 0.0),
                  "cmd_throttle": None, "cmd_pitch": None},
        "target": hedef,
        "distance_m": t.get("mesafe_m"),
        "gercek_mesafe_m": t.get("gercek_mesafe_m"),
        "debug": {"available": False},             # bozuk-GNSS kıyası bizde YOK
        "j": {}, "kiyas": {}, "gnss": {},          # J filtresi paneli bizde YOK
        "kip": kip_oku(),
        "gorev_aktif": bool(g("gorsel_aktif", 0)) or durum not in ("-", ""),
        "manuel_aktif": False,
        "kaynak": Ayar.GPS_KAYNAK,
        "gorsel": gorsel,
        "olaylar": [],                             # olay günlüğü bizde YOK
        "gudum": {"faz": durum, "bekci": g("bekci", "")},
        "takip": takip,
        "gorev": {"faz": durum, "ist_hata_m": t.get("ist_hata_m")},
        # kare kaynağı: ok=False ise FPV oyunu DEĞİL başka bir pencereyi
        # gösteriyor demektir (bkz. kaynak_isaretle)
        "kaynak_kare": {"ok": _kaynak["ok"], "hud": round(_kaynak["hud"], 3)},
    }


def _kilit_suresi():
    """Son KILIT_WIN_S saniyede KÜMÜLATİF kilitli süre (s)."""
    if not _kilit_pencere:
        return 0.0
    simdi = _kilit_pencere[-1][0]
    top = 0.0
    onceki = None
    for t, k in _kilit_pencere:
        if simdi - t > KILIT_WIN_S:
            onceki = t
            continue
        if onceki is not None and k:
            # ⛔ KREDİ TAVANI ŞARTNAMEDEN gelir, keyfi 0.5 s DEĞİL:
            #   "5 saniyelik bir kilitlenme için %5'lik yani 200 ms'ye kadar
            #   tolerans mevcuttur." Uzun tespit boşluğu kilit süresi SAYILMAZ.
            top += min(t - onceki, Ayar.KILIT_DT_MAX_S)
        onceki = t
    return top


def kilit_degerlendir(tespit, W=1920.0, H=1080.0):
    """Bu karede yarışma kilidi var mı — HESAP, çizim YOK.
    Dönüş: (kilitli_mi, av_icinde_mi, kaplama_yuzde)."""
    if not tespit:
        _kilit_pencere.append((time.time(), False))
        return False, False, 0.0
    cx, cy, w, h = tespit[0], tespit[1], tespit[2], tespit[3]
    # ⭐ ÖLÇÜTÜN TEK KAYNAĞI: dow/gudum/kilit.py (güdüm de onu kullanır).
    kl, _sebep = _KILIT_OLCUT.kare_kilitli(tespit)
    av = (_sebep != "AV_disi")
    kap = max(w / max(W, 1.0), h / max(H, 1.0))
    _kilit_pencere.append((time.time(), kl))
    return kl, av, 100.0 * kap


# =============================================================================
#  KAYNAK KAPISI — yayınlanan kare GERÇEKTEN oyun mu?
# -----------------------------------------------------------------------------
#  ⛔ Yakalama pencereye değil TÜM EKRANA bakıyor (`kadraj.BOLGE` = 0,0,1920x1080).
#     Oyunun üstüne başka bir pencere gelirse (en tipik hâli: paneli AYNI
#     monitörde açmak) panel oyunu değil O PENCEREYİ yayınlar ve operatör
#     bunu fark etmez — FPV canlı görünür ama başka bir şeyi gösterir.
#     ÖLÇÜLDÜ (2026-08-25): oyun görünürken HUD parlaklığı 0.126, tarayıcı
#     üstüne gelince 0.001.
#  Çözüm: kare, `kosu.py` yakalama ipliğinde HUD imzasıyla sınanır; imza yoksa
#  kare YAYINLANMAZ (son iyi kare durur) ve burada uyarı bayrağı kalkar.
#  Arayüz bu bayrağı görüp "oyun penceresi kapalı" uyarısı basar.
# =============================================================================
_kaynak = {"ok": True, "hud": 0.0, "t": 0.0}


def kaynak_isaretle(ok, hud=0.0):
    """Yakalama ipliği her karede çağırır: kare oyun muydu?"""
    _kaynak["ok"] = bool(ok)
    _kaynak["hud"] = float(hud)
    _kaynak["t"] = time.time()


def fps_isaretle(ad):
    _fps[ad].append(time.time())


def telem_yaz(d):
    """Güdüm telemetrisini panele SÜREÇ İÇİ yaz (HTTP yok)."""
    with _kosul:
        t = dict(_K["telem"]); t.update(d); _K["telem"] = t


def tespit_isaretle(var):
    """Tespit şeridine BİR ÇIKARIM sonucu yaz.

    ⚠ Şerit, GÖSTERİM karesi başına değil ÇIKARIM başına işaretlenir.
      Yakalama 15 Hz, çıkarım 5 Hz; her gösterim karesinde işaretlemek
      aynı sonucu 3 kez sayardı ve oranı OLDUĞUNDAN İYİ gösterirdi."""
    _serit.append((time.time(), 1 if var else 0))


def kare_koy(img_rgb, tespit=None, telem=None, kalite=62, olcek=0.5):
    """Bir kareyi (ve varsa tespit kutusunu) panele bas."""
    try:
        # ⚡ ÖNCE küçült, SONRA çevir+çiz: tüm çizim 1/4 piksel üzerinde olur.
        #   Ölçülen: img[:,:,::-1].copy() 8.62 ms vs cvtColor 0.15 ms (57 kat).
        o = olcek
        kck = cv2.resize(img_rgb, None, fx=o, fy=o,
                         interpolation=cv2.INTER_LINEAR) if o != 1.0 else img_rgb
        # ⭐ 2026-08-25: kare artık BGR geliyor (kadraj.grab_bgr). Eskiden
        #   burada RGB2BGR çevrimi vardı; kaynak düzelince GEREKSİZ oldu ve
        #   kaldırıldı — bir çevrim de kazandık (ölçüldü: 0.15 ms/kare).
        im = np.ascontiguousarray(kck)
        hh, ww = im.shape[:2]
        zoom = None
        odak = None

        if tespit is not None:
            cx, cy, w, h = [v * o for v in tespit[:4]]
            conf = tespit[4]
            # ⭐ KUTU DURUMU RENKLE KODLANIR (yer-kontrol `model-fps` arayüzünden).
            #   Sürekliliği GÖZLE ayırt edebilmek için: kutunun O KAREDE gerçekten
            #   ölçülmüş mü yoksa öngörülmüş mü olduğunu görmeden "kesintisiz
            #   takip" iddiası doğrulanamaz.
            #     YEŞİL düz    = dedektör o karede GERÇEKTEN buldu (eşleşme)
            #     TURUNCU kesik= takipçi Kalman ile ÖNGÖRDÜ (coast) — ölçüm YOK
            kaynak = (_K["telem"] or {}).get("takip_kaynak", "")
            ongoru = (kaynak == "tahmin")
            renk = (60, 170, 255) if ongoru else (60, 255, 60)   # BGR
            x1, y1 = int(cx - w / 2), int(cy - h / 2)
            x2, y2 = int(cx + w / 2), int(cy + h / 2)
            if ongoru:      # kesikli dikdörtgen (cv2'de yok — elle çiz)
                adim = 9
                for xx in range(x1, x2, adim * 2):
                    cv2.line(im, (xx, y1), (min(xx + adim, x2), y1), renk, 2)
                    cv2.line(im, (xx, y2), (min(xx + adim, x2), y2), renk, 2)
                for yy in range(y1, y2, adim * 2):
                    cv2.line(im, (x1, yy), (x1, min(yy + adim, y2)), renk, 2)
                    cv2.line(im, (x2, yy), (x2, min(yy + adim, y2)), renk, 2)
            else:
                cv2.rectangle(im, (x1, y1), (x2, y2), renk, 2)
            # köşe işaretleri — küçük kutuyu gözle bulmayı kolaylaştırır
            L = max(10, int(0.6 * max(w, h)))
            for (px, py, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1),
                                     (x1, y2, 1, -1), (x2, y2, -1, -1)):
                cv2.line(im, (px, py), (px + dx * L, py), renk, 3)
                cv2.line(im, (px, py), (px, py + dy * L), renk, 3)
            # ⭐ YARIŞMA KİLİDİ — yalnız HESAP; çizimi arayüz yapar.
            _kl, _av, _kap = kilit_degerlendir(
                (cx / o, cy / o, w / o, h / o), ww / o, hh / o)
            _K["telem"]["kilit_simdi"] = int(_kl)
            _K["telem"]["kilit_av"] = int(_av)
            _K["telem"]["kilit_kaplama"] = round(_kap, 2)
            _K["telem"]["kilit_pencere_s"] = round(_kilit_suresi(), 2)
            _t = _K["telem"] or {}
            _et = f"{conf:.2f}"
            if _t.get("takip_id", -1) not in (-1, None):
                _et += f"  ID{_t['takip_id']}"
                if ongoru:
                    _et += f"  ONGORU+{_t.get('takip_coast', 0)}"
            cv2.putText(im, _et, (x2 + 6, max(18, int(cy))),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, renk, 2)
            odak = (cx, cy, renk)

        if tespit is None:
            kilit_degerlendir(None)              # kilitsiz kare de pencereye girer
            _K["telem"]["kilit_simdi"] = 0
            _K["telem"]["kilit_pencere_s"] = round(_kilit_suresi(), 2)

        # ⭐ AV — HEDEF VURUŞ ALANI (Teknofest Şekil 2). Soldan/sağdan %25,
        #   üstten/alttan %10 kırpılmış dikdörtgen. Kilit ancak hedefin
        #   MERKEZİ bunun içindeyken sayılır; operatör bunu GÖRMELİ.
        #   ⚠ YALNIZ ÇİZİM — hiçbir güdüm kararı bu satırlardan geçmez.
        _ax0, _ax1 = int(KILIT_AV_X * ww), int((1.0 - KILIT_AV_X) * ww)
        _ay0, _ay1 = int(KILIT_AV_Y * hh), int((1.0 - KILIT_AV_Y) * hh)
        _avr = (90, 190, 90) if _K["telem"].get("kilit_av") else (110, 110, 110)
        for _xx in range(_ax0, _ax1, 26):          # kesikli çerçeve
            cv2.line(im, (_xx, _ay0), (min(_xx + 13, _ax1), _ay0), _avr, 1)
            cv2.line(im, (_xx, _ay1), (min(_xx + 13, _ax1), _ay1), _avr, 1)
        for _yy in range(_ay0, _ay1, 26):
            cv2.line(im, (_ax0, _yy), (_ax0, min(_yy + 13, _ay1)), _avr, 1)
            cv2.line(im, (_ax1, _yy), (_ax1, min(_yy + 13, _ay1)), _avr, 1)
        cv2.putText(im, "AV", (_ax0 + 4, _ay0 + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, _avr, 1)
        # kadraj merkezi
        cv2.line(im, (ww // 2 - 14, hh // 2), (ww // 2 + 14, hh // 2), (255, 170, 0), 1)
        cv2.line(im, (ww // 2, hh // 2 - 14), (ww // 2, hh // 2 + 14), (255, 170, 0), 1)

        # yakın kesit (her 2. karede — maliyet yarıya iner)
        if odak is not None and (_K["sayac"] % 2 == 0):
            cx, cy, renk = odak
            k = int(100 * o)
            zx1, zy1 = max(0, int(cx) - k), max(0, int(cy) - k)
            zx2, zy2 = min(ww, int(cx) + k), min(hh, int(cy) + k)
            if zx2 - zx1 > 24 and zy2 - zy1 > 24:
                z = cv2.resize(im[zy1:zy2, zx1:zx2], (400, 400),
                               interpolation=cv2.INTER_NEAREST)
                cv2.rectangle(z, (0, 0), (399, 399), renk, 2)
                ok2, zb = cv2.imencode(".jpg", z, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
                if ok2:
                    zoom = zb.tobytes()

        ok, buf = cv2.imencode(".jpg", im, [int(cv2.IMWRITE_JPEG_QUALITY), kalite])
        if not ok:
            return
        with _kosul:
            _K["jpg"] = buf.tobytes()
            if zoom is not None:
                _K["zoom"] = zoom
            if telem is not None:
                _K["telem"] = telem
            _K["sayac"] += 1
            _kosul.notify_all()        # MJPEG yazıcılarını UYANDIR
    except Exception:
        pass


def _serit_ozet(pencere=20.0):
    simdi = time.time()
    son = [(t, d) for t, d in _serit if simdi - t <= pencere]
    if not son:
        return [], 0.0
    n = len(son)
    tesp = sum(1 for _, d in son if d == 1)
    return [d for _, d in son][-140:], 100.0 * tesp / n


_HTML = """<!doctype html><meta charset=utf-8><title>DoW — Görüş Analizi</title>
<style>
:root{--bg:#0a0c10;--k:#141922;--ç:#222c3a;--y:#e6edf5;--s:#8b98a8;--v:#4ade80}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--y);
     font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.üst{display:flex;align-items:center;gap:18px;padding:10px 16px;
     background:var(--k);border-bottom:1px solid var(--ç)}
.üst h1{margin:0;font-size:14px;letter-spacing:.14em;text-transform:uppercase;color:var(--s)}
.fps{display:flex;gap:16px;margin-left:auto}
.fps div{text-align:right}
.fps b{display:block;font-size:19px;font-variant-numeric:tabular-nums;color:var(--v)}
.fps b em{font-style:normal;font-size:11px;color:var(--s)}
.fps span{font-size:10px;letter-spacing:.1em;color:var(--s);text-transform:uppercase}
.gövde{display:grid;grid-template-columns:1fr 330px;gap:14px;padding:14px}
.kart{background:var(--k);border:1px solid var(--ç);border-radius:10px;overflow:hidden}
.kart h2{margin:0;padding:8px 12px;font-size:11px;letter-spacing:.12em;color:var(--s);
         text-transform:uppercase;border-bottom:1px solid var(--ç)}
#v{display:block;width:100%;background:#000}
#z{display:block;width:100%;image-rendering:pixelated;background:#000}
.satır{display:flex;justify-content:space-between;padding:5px 12px;
       border-bottom:1px solid #1a212c;font-variant-numeric:tabular-nums}
.satır:last-child{border:0}
.satır i{font-style:normal;color:var(--s)}
.satır b{font-weight:600}
#şerit{display:flex;gap:1px;height:34px;padding:8px 12px;align-items:stretch}
#şerit i{flex:1;border-radius:1px;background:#25303f}
#şerit i.d{background:var(--v)}
.açk{display:flex;gap:14px;padding:6px 12px 10px;font-size:11px;color:var(--s)}
.açk s{text-decoration:none;display:inline-block;width:10px;height:10px;
       border-radius:2px;margin-right:5px;vertical-align:-1px}
.büyük{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;
       padding:6px 12px 12px}
.kip{display:flex;gap:8px;margin-left:24px}
.kip button{background:#1a2230;color:#8b98a8;border:1px solid var(--ç);
  border-radius:7px;padding:7px 18px;cursor:pointer;font:600 12px/1 inherit;
  letter-spacing:.1em;text-transform:uppercase;transition:.12s}
.kip button:hover{border-color:#3d4a5c;color:#c8d2de}
.kip button.on{background:#1d4ed8;border-color:#3b82f6;color:#fff}
.kip button.on.g{background:#15803d;border-color:#22c55e}
.kip button.on.v{background:#b45309;border-color:#f59e0b}
</style>
<div class=üst>
  <h1>DoW · Görüş Analizi</h1>
  <div class=kip>
    <button id=k_hibrit onclick="kip('hibrit')">Hibrit</button>
    <button id=k_gps    onclick="kip('gps')">GPS</button>
    <button id=k_gorsel onclick="kip('gorsel')">Görsel</button>
  </div>
  <!-- ⚠ §0.1: panelde AYNI ANDA EN FAZLA BİR yeni özellik durur. -->
  <div class=kip>
    <button id=o_hizli onclick="ozellik('isp')">🧵 Ö-M GÖRÜŞ İŞ PARÇACIĞI</button>
  </div>
  <div class=fps>
    <div><b id=f1>—</b><span>yakalama</span></div>
    <div><b id=f2>—</b><span>dedektör</span></div>
    <div><b id=f3>—</b><span>ekran</span></div>
  </div>
</div>
<div class=gövde>
  <div>
    <div class=kart><h2>FPV — dedektör kutusu</h2><img id=v src="/video"></div>
    <div class=kart style="margin-top:14px">
      <h2>Tespit sürekliliği — son 20 saniye</h2>
      <div id=şerit></div>
      <div class=açk>
        <span><s style="background:#4ade80"></s>dedektör bir kutu verdi</span>
        <span><s style="background:#25303f"></s>kutu yok</span>
        <span><s style="background:#ffaa3c"></s>turuncu KESİK kutu = takipçi öngörüsü (ölçüm yok)</span>
        <span>⚠ bu oran HAM tespittir — kutunun DOĞRU yerde olup olmadığını
        söylemez, gözle bak</span>
      </div>
      <div class=büyük><span id=or1 style="color:#4ade80">—</span>
        <span style="font-size:13px;color:#8b98a8"> ham tespit oranı</span></div>
    </div>
  </div>
  <div>
    <div class=kart><h2>Hedef — 4× yakın</h2><img id=z src="/zoom"></div>
    <div class=kart style="margin-top:14px"><h2>Durum</h2><div id=t></div></div>
  </div>
</div>
<script>
const AL=[["kip","güdüm kipi"],["durum","faz"],
  ["vis_conf","güven"],["vis_kutu_px","kutu px"],["vis_menzil","menzil (kutu)"],
  ["imgsz","çıkarım boyu"],
  ["takip_id","iz kimliği"],["takip_kaynak","kutu kaynağı"],
  ["takip_coast","öngörü karesi"],["takip_n","aktif iz"],
  ["det_ms","çıkarım ms"],
  ["ist_hata_m","istasyon hata"],
  ["ist_hata_dikey","istasyon hata dikey"],["hedef_menzil_m","hedefe menzil"],
  ["drone_hiz","hız m/s"],["v_istek","istenen hız"],["bekci","bekçi"]];
let son=0;
async function kip(k){
  await fetch('/kip',{method:'POST',body:JSON.stringify({kip:k})});
  kipGoster(k);
}
function kipGoster(k){
  for(const [ad,snf] of [['hibrit',''],['gps','g'],['gorsel','v']]){
    const b=document.getElementById('k_'+ad);
    b.className = (ad===k) ? ('on '+snf) : '';
  }
}
// ⚠ §0.1: panelde sınanan özellik YOK; düğme de yok. Yeni özellik
//   eklenince bu iki işlev ona bağlanır (git tarihçesi: Ö-I / Ö-J).
//   ⛔ ozellikGoster'in ESKİ hâli silinen düğmeyi arıyordu; düğme
//      yokken getElementById null döner ve telemetri döngüsü ÇÖKERDİ.
async function ozellik(a){
  const r=await (await fetch('/ozellik',{method:'POST',
                 body:JSON.stringify({ad:a})})).json();
  ozellikGoster(r.acik);
}
function ozellikGoster(v){
  const b=document.getElementById('o_hizli');
  if(!b) return;                      // düğme yoksa sessizce geç
  b.className = v ? 'on v' : '';
  b.textContent = v ? '🧵 Ö-M İŞ PARÇACIĞI: AÇIK' : '🧵 Ö-M İŞ PARÇACIĞI: kapalı';
}
function fps(el,v,tav){
  document.getElementById(el).innerHTML =
    (v||0).toFixed(1) + (tav ? ' <em>/ '+tav.toFixed(0)+'</em>' : '');
}
async function tik(){
 try{
  const d=await (await fetch('/telem')).json();
  fps('f1',d._fps_yakala,d._tavan_yakala);
  fps('f2',d._fps_dedektor,d._tavan_dedektor);
  fps('f3',d._fps_ekran,0);
  let h='';
  for(const [k,ad] of AL){ if(d[k]===undefined)continue;
    let v=d[k]; if(typeof v==='number')v=Math.abs(v)<1000?v.toFixed(2):v.toFixed(0);
    h+=`<div class=satır><i>${ad}</i><b>${v}</b></div>`;}
  document.getElementById('t').innerHTML=h;
  const s=d._serit||[];
  document.getElementById('şerit').innerHTML=
    s.map(x=>`<i class="${x===1?'d':''}"></i>`).join('');
  document.getElementById('or1').textContent='%'+(d._oran_tespit||0).toFixed(0);
  if(d.kip) kipGoster(d.kip);
  if(d._hizli!==undefined) ozellikGoster(d._hizli);
 }catch(e){}
}
setInterval(tik,220);
setInterval(()=>{document.getElementById('z').src='/zoom?'+(son++)},150);
</script>"""



# =============================================================================
#  TALON KÖPRÜSÜ — panelden HEDEF İHA'yı sürmek için dosya kanalı
# -----------------------------------------------------------------------------
#  ⛔ Resmî SDK (TCP 12345) Talon'a KOMUT VEREMEZ — yalnızca `get_target_*`
#     okur; bütün `set_*` çağrıları avcı drone'a aittir. Bu yüzden komutlar
#     dosya üzerinden oyundaki UE4SS moduna (TalonWebControl) aktarılır:
#         panel  ->  /tmp/talon_kopru.txt  ->  (Z: sürücüsü)  ->  oyun
#     Proton önekinin Z: sürücüsü tüm Linux dosya sistemini gördüğü için
#     oyun tarafı aynı dosyayı `Z:\tmp\talon_kopru.txt` olarak okur.
#
#  BİÇİM (tek satır):  <aktif> <throttle> <yaw> <pitch> <roll> <sayaç>
#     aktif    0/1    : serbest uçuş açık mı
#     throttle 0..1   : ileri hız (oyun tarafı 300..4000 cm/s'ye eşler)
#     yaw      -1..1  : burun sola / sağa
#     pitch    -1..1  : alçal / tırman
#     roll     -1..1  : sola / sağa yatış (koordineli dönüş de üretir)
#  ⛔ 7. ALAN (kip) SİLİNDİ (2026-08-27, §5.12 — kullanıcı kararı): kare ve
#     daire desenleri hem gerçekçi değildi hem de oyun tarafında hedefin
#     parçalarını koparıyordu. Mod tarafındaki karşılığı da çıkarıldı
#     (`dow/ue4ss_modlari/.../main.lua` 267 -> 175 satır). Elle kumanda
#     (eski kip 0) DURUYOR — `araclar/manevra.py` onu kullanıyor.
#     sayaç           : her yazmada artar; oyun tarafı bununla arayüzün
#                       donup donmadığını anlar (bayatlarsa eksenler sıfırlanır)
#
#  Yazma ATOMİK: önce .tmp, sonra os.replace — oyun yarım satır okumaz.
# =============================================================================
TALON_KOPRU_YOL = os.environ.get("DOW_TALON_KOPRU", "/tmp/talon_kopru.txt")
_talon_sayac = 0
_talon_kilit = threading.Lock()


def talon_kopru_yaz(d):
    """Panelden gelen eksen komutlarını köprü dosyasına yazar. True/False döner."""
    global _talon_sayac

    def _eksen(x, alt, ust, varsayilan=0.0):
        try:
            v = float(x)
        except Exception:
            return varsayilan
        if v != v:                       # NaN
            return varsayilan
        return max(alt, min(ust, v))

    aktif = 1 if d.get("aktif") else 0
    thr = _eksen(d.get("throttle", 0.0), 0.0, 1.0)
    yaw = _eksen(d.get("yaw", 0.0), -1.0, 1.0)
    pit = _eksen(d.get("pitch", 0.0), -1.0, 1.0)
    rol = _eksen(d.get("roll", 0.0), -1.0, 1.0)
    with _talon_kilit:
        _talon_sayac += 1
        satir = "%d %.3f %.3f %.3f %.3f %d\n" % (
            aktif, thr, yaw, pit, rol, _talon_sayac)
        gecici = TALON_KOPRU_YOL + ".tmp"
        try:
            with open(gecici, "w") as f:
                f.write(satir)
            os.replace(gecici, TALON_KOPRU_YOL)
            return True
        except Exception as e:
            print("[panel] Talon köprüsü yazılamadı (%s): %s" % (TALON_KOPRU_YOL, e),
                  flush=True)
            return False



class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _gonder(self, gövde, tip, kod=200):
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(gövde)))
        self.end_headers()
        self.wfile.write(gövde)

    def do_GET(self):
        yol = self.path.split("?")[0]
        if yol == "/":
            # ⭐ YER-KONTROL ARAYÜZÜ (2026-08-24, kullanıcı isteği): kullanıcının
            #   attığı `avci-drone-yer-kontrol` deposunun `model-fps` branch'indeki
            #   `web/index.html` AYNEN kullanılır. Dosya varsa o servis edilir;
            #   yoksa sade panele (`_HTML`) düşülür — arayüz dosyası eksikse
            #   uçuş yine izlenebilsin (zarif bozulma).
            _y = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "web", "index.html")
            if os.path.exists(_y):
                with open(_y, "rb") as f:
                    return self._gonder(f.read(), "text/html; charset=utf-8")
            return self._gonder(_HTML.encode(), "text/html; charset=utf-8")
        if yol == "/sade":                    # eski sade panel (kıyas/yedek)
            return self._gonder(_HTML.encode(), "text/html; charset=utf-8")
        if yol == "/api/telemetry":
            return self._gonder(json.dumps(_api_telemetry()).encode(),
                                "application/json")
        if yol in ("/api/tune_rapor", "/api/tune"):
            # Canlı kaydırıcı paneli bizde YOK (panel tasarım kararı: ayarları
            # yapay zekâ değiştirir). Boş dönülür, arayüz listeyi boş çizer.
            return self._gonder(b"{}", "application/json")
        if yol == "/telem":
            serit, o1 = _serit_ozet()
            with _kosul:
                t = dict(_K["telem"])
            from dow.ayarlar import kip_oku
            t["kip"] = kip_oku()
            from dow.gorus.tracker import TakipCfg
            t["_hizli"] = int(TakipCfg.AKTIF)
            t.update({"_serit": serit, "_oran_tespit": o1,
                      "_fps_yakala": _hz(_fps["yakala"]),
                      "_fps_dedektor": _hz(_fps["dedektor"]),
                      "_fps_ekran": _hz(_fps["ekran"]),
                      "_tavan_yakala": _TAVAN["yakala"],
                      "_tavan_dedektor": _TAVAN["dedektor"]})
            return self._gonder(json.dumps(t).encode(), "application/json")
        if yol == "/zoom":
            with _kosul:
                z = _K["zoom"]
            if not z:
                self.send_response(404); self.send_header("Content-Length", "0")
                self.end_headers(); return
            return self._gonder(z, "image/jpeg")
        if yol == "/video":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=k")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            son = -1
            try:
                while True:
                    # ⚡ KOŞUL DEĞİŞKENİ: yeni kare gelene kadar UYU.
                    #   Eski sürüm 4 ms'de bir boşuna uyanıyordu (250 Hz).
                    with _kosul:
                        if _K["sayac"] == son or _K["jpg"] is None:
                            _kosul.wait(timeout=1.0)
                        jpg, c = _K["jpg"], _K["sayac"]
                    if jpg is None or c == son:
                        continue
                    son = c
                    fps_isaretle("ekran")
                    self.wfile.write(b"--k\r\nContent-Type: image/jpeg\r\n"
                                     b"Content-Length: " + str(len(jpg)).encode() +
                                     b"\r\n\r\n" + jpg + b"\r\n")
            except Exception:
                return
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self):
        # ⭐ YER-KONTROL ARAYÜZÜNÜN UÇLARI (dow/web/index.html)
        if self.path == "/api/command":
            n = int(self.headers.get("Content-Length", 0))
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                d = {}
            cmd = str(d.get("cmd", ""))
            if cmd == "vismode":
                # Onların kipi -> bizimki. OTO = hibrit (GPS ile yaklaş,
                # görsel temas kurulunca devret) — bizde karşılığı budur.
                esle = {"OTO": "hibrit", "GPS": "gps", "GORSEL": "gorsel"}
                k = esle.get(str(d.get("mode", "")).upper())
                if k:
                    from dow.ayarlar import Ayar, kip_yaz
                    Ayar.GUDUM_KIPI = k
                    kip_yaz(k)
                    telem_yaz({"kip": k})
                    print("[panel] GÜDÜM KİPİ -> %s" % k.upper(), flush=True)
                    return self._gonder(
                        json.dumps({"ok": True, "msg": "Güdüm: %s" % k}).encode(),
                        "application/json")
            if cmd == "basla":
                if _basla.is_set():
                    return self._gonder(json.dumps(
                        {"ok": False, "msg": "Görev zaten başladı"}).encode(),
                        "application/json")
                _basla.set()
                print("[panel] ⭐ GÖREV BAŞLAT — panelden tetiklendi", flush=True)
                return self._gonder(json.dumps(
                    {"ok": True, "msg": "Görev başladı"}).encode(),
                    "application/json")
            if cmd == "takip":
                from dow.gorus.tracker import TakipCfg
                TakipCfg.AKTIF = not TakipCfg.AKTIF
                telem_yaz({"_hizli": int(TakipCfg.AKTIF)})
                print("[panel] TAKİP -> %s"
                      % ("AÇIK" if TakipCfg.AKTIF else "kapalı"), flush=True)
                return self._gonder(json.dumps(
                    {"ok": True, "acik": int(TakipCfg.AKTIF),
                     "msg": "Takipçi: %s" % ("AÇIK" if TakipCfg.AKTIF else "kapalı")
                     }).encode(), "application/json")
            # ⛔ Görev başlat/durdur onların sunucusunda var, bizde YOK:
            #    uçuşu `araclar/kosu.py` süreci yönetir. Uydurma cevap
            #    vermek yerine açıkça söylüyoruz.
            return self._gonder(json.dumps(
                {"ok": False,
                 "msg": "'%s' bu sistemde yok — uçuşu kosu.py yönetir" % cmd
                 }).encode(), "application/json")
        if self.path == "/api/talon":
            # HEDEF İHA elle kontrol — eksenleri köprü dosyasına yaz.
            n = int(self.headers.get("Content-Length", 0))
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                d = {}
            ok = talon_kopru_yaz(d)
            return self._gonder(json.dumps({"ok": ok}).encode(),
                                "application/json")
        if self.path in ("/api/manuel", "/api/tune"):
            # Manuel RC ve canlı kaydırıcılar bizde YOK (ayarları yapay zekâ
            # değiştirir — panel tasarım kararı). Sessizce yutulur ki arayüz
            # hata vermesin.
            n = int(self.headers.get("Content-Length", 0))
            try:
                self.rfile.read(n)
            except Exception:
                pass
            return self._gonder(b'{"ok":false,"msg":"bu sistemde yok"}',
                                "application/json")
        if self.path == "/kip":
            n = int(self.headers.get("Content-Length", 0))
            try:
                from dow.ayarlar import Ayar, kip_yaz
                k = json.loads(self.rfile.read(n) or b"{}").get("kip", "hibrit")
                if k not in ("hibrit", "gps", "gorsel"):
                    raise ValueError(k)
                Ayar.GUDUM_KIPI = k
                kip_yaz(k)          # ayrı süreçte koşan araçlar buradan okur
                telem_yaz({"kip": k})
                print(f"[panel] GÜDÜM KİPİ -> {k.upper()}", flush=True)
                self._gonder(json.dumps({"ok": True, "kip": k}).encode(),
                             "application/json")
            except Exception as e:
                self._gonder(json.dumps({"ok": False, "hata": str(e)}).encode(),
                             "application/json", 400)
            return
        if self.path == "/ozellik":
            # ⭐ PANELDEKİ TEK ÖZELLİK (CLAUDE.md §0.1) — KİLİT FAZI.
            #   Ö-M (görüş iş parçacığı) 2026-08-27'de ELENDİ; §0.1 gereği
            #   panelde aynı anda tek özellik durur, o yüzden düğme bu
            #   adımın özelliğine devredildi.
            #
            #   KİLİT FAZI (Teknofest 6.1.4): görsel temas kurulunca araç
            #   DOĞRUDAN vuruşa gitmez; önce ~6 m mesafe tutup hedefi
            #   AV dörtgeninde %6 büyüklüğünde tutar ve 10 saniyelik
            #   pencerede kümülatif 5 saniye kilit biriktirir. İsteri
            #   sağlanınca TERMİNAL faza geçip vuruşa gider.
            #   Kapalıyken güdüm BİT BİT eski davranıştır (bekçi B63).
            n = int(self.headers.get("Content-Length", 0))
            try:
                self.rfile.read(n)
                from dow.ayarlar import Ayar
                acik = not Ayar.KILIT_FAZI
                Ayar.KILIT_FAZI = acik
                telem_yaz({"_kilit_fazi": int(acik)})
                print("[panel] KİLİT FAZI -> %s"
                      % ("AÇIK" if acik else "kapalı"), flush=True)
                self._gonder(json.dumps({"ok": True, "acik": int(acik)}).encode(),
                             "application/json")
            except Exception as e:
                self._gonder(json.dumps({"ok": False, "hata": str(e)}).encode(),
                             "application/json", 400)
            return
        if self.path != "/telem":
            self.send_response(404); self.send_header("Content-Length", "0")
            self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0))
        try:
            telem_yaz(json.loads(self.rfile.read(n) or b"{}"))
            self._gonder(b'{"ok":true}', "application/json")
        except Exception as e:
            self._gonder(json.dumps({"ok": False, "hata": str(e)}).encode(),
                         "application/json", 400)


def baslat(port=8801, tavan_yakala=None, tavan_dedektor=None):
    from dow.ayarlar import Ayar
    _TAVAN["yakala"] = (Ayar.PANEL_YAKALA_HZ if tavan_yakala is None
                        else tavan_yakala)
    _TAVAN["dedektor"] = (Ayar.PANEL_DET_HZ if tavan_dedektor is None
                          else tavan_dedektor)
    s = ThreadingHTTPServer(("127.0.0.1", port), _H)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    print(f"[panel] http://127.0.0.1:{port}", flush=True)
    return s
