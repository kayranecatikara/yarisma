# -*- coding: utf-8 -*-
"""
================================================================================
DRONE YER KONTROL PANELİ — canlı video + telemetri + MANUEL KUMANDA
================================================================================
Adres: http://<drone-bilgisayari>:8810

ÜÇ İŞİ VAR:
  1. GÖSTER  : canlı FPV, AV kilit dörtgeni, telemetri, sağlık
  2. SÜR     : iki sanal joystick ile MANUEL kontrol
  3. SEÇ     : MANUEL / OTONOM kipi ve ARM

⛔⛔ ÇUBUKLAR DOĞRUDAN ELRS'E GİTMEZ — HAKEMDEN (`komut.py`) GEÇER.
   Sebep: hakem, fiziksel kumandayı panele göre ÖNCELİKLİ tutar, bekçi
   zamanlayıcılarını işletir ve arm kuralını uygular. Paneli doğrudan
   bağlamak, o emniyet zincirini atlamak olurdu.

⛔ ARM KURALI: arm bir İNSAN kaynağından gelir (fiziksel kumanda ya da bu
   panel), GÜDÜMDEN ASLA. Panelde arm düğmesi BASILI TUTMA ister — tek
   tıkla yanlışlıkla arm edilemesin.

⚠ PANEL ÇUBUKLARI BAYATLARSA (sekme kapandı, WiFi düştü, sayfa dondu)
  hakem 0.5 s içinde onları YOK sayar. Donmuş bir çubuk değerini komut
  sanmak, aracı son verilen komutla sonsuza dek uçurmaktır.
================================================================================
"""
import base64
import hashlib
import json
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_D = {"kamera": None, "komut": None, "baglanti": None, "hedef": None,
      "sunucu": None, "kilitci": None, "beyin": None, "dikey": None,
      "son_kutu": None, "olcut": None, "ham_kutu": None,
      "ham_sebep": "", "kayit": None, "gorsel_aktif": False,
      "rtl": None}
_kosul = threading.Condition()
_kare_sayac = [0]


def kur(**kw):
    """Panelin okuyacağı nesneleri bağla (hepsi isteğe bağlı)."""
    _D.update({k: v for k, v in kw.items() if k in _D})


def kare_bildir():
    with _kosul:
        _kare_sayac[0] += 1
        _kosul.notify_all()


# ======================================================================
#  WEBSOCKET — panelin ANA kanalı
# ======================================================================
# ⛔⛔ NİYE WEBSOCKET — HTTP İSTEK YIĞINI PANELİ DONDURUYORDU (2026-08-29):
#   Panelin üç ayrı akışı vardı: 30 Hz çubuk POST'u, 5 Hz durum GET'i,
#   15 Hz kare isteği. Hepsi AYNI kaynağa gidiyor ve Chrome'un HTTP/1.1
#   için kaynak başına eşzamanlı bağlantı sınırı 6'dır. ~50 istek/s bu
#   havuza binince tarayıcı istekleri KUYRUĞA alır; kuyruk büyüdükçe
#   arayüz tepkisiz görünür ve DÜĞME TIKLAMALARI BİLE GEÇMEZ.
#   ⭐ ÖLÇÜLDÜ: sunucu bu sırada kip değişikliğini 0.5 ms'de işliyordu —
#     yani sorun HİÇBİR ZAMAN sunucuda değildi, tarayıcının kuyruğundaydı.
#
#   WebSocket bunu KÖKÜNDEN kaldırır: TEK kalıcı bağlantı, çift yönlü,
#   istek/yanıt yükü yok, kuyruk yok. Çubuklar yukarı, durum aşağı, hepsi
#   o tek kanaldan. Havuzda 5 boş slot kalır (kareler için fazlasıyla).
#
# ⚠ SAF STDLIB: harici kütüphane yok (panel sahada internetsiz çalışır).
#   El sıkışma RFC 6455'in kendisidir; çerçeveleme aşağıda.
#
# ⛔ HTTP YOLU SİLİNMEDİ: WebSocket kurulamazsa istemci kendiliğinden
#   eski yola düşer. Tek yol bırakmak, yeni bir tek arıza noktası olurdu.

_WS_SIHIR = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_ws_istemciler = set()
_ws_kilit = threading.Lock()


def _ws_cerceve(veri, opkod=0x1):
    """Sunucu -> istemci çerçevesi (maskesiz)."""
    n = len(veri)
    bas = bytes([0x80 | opkod])
    if n < 126:
        bas += bytes([n])
    elif n < 65536:
        bas += bytes([126]) + struct.pack(">H", n)
    else:
        bas += bytes([127]) + struct.pack(">Q", n)
    return bas + veri


def _ws_oku(rfile):
    """İstemci -> sunucu çerçevesi. Döner: (opkod, yuk) ya da None."""
    bas = rfile.read(2)
    if len(bas) < 2:
        return None
    b1, b2 = bas[0], bas[1]
    opkod = b1 & 0x0F
    maskeli = b2 & 0x80
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", rfile.read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rfile.read(8))[0]
    if n > 1 << 20:                      # 1 MB üstü çerçeve kabul edilmez
        return None
    maske = rfile.read(4) if maskeli else b"\x00" * 4
    yuk = bytearray(rfile.read(n))
    if maskeli:
        for i in range(n):
            yuk[i] ^= maske[i & 3]
    return opkod, bytes(yuk)


def _ws_yayinla():
    """Bağlı bütün panellere durum gönder. Kendi iş parçacığında koşar."""
    while True:
        time.sleep(0.1)                  # 10 Hz
        with _ws_kilit:
            istemciler = list(_ws_istemciler)
        if not istemciler:
            continue
        try:
            veri = json.dumps(_durum()).encode("utf-8")
        except Exception:
            continue
        cer = _ws_cerceve(veri)
        for c in istemciler:
            try:
                c.sendall(cer)
            except Exception:
                with _ws_kilit:
                    _ws_istemciler.discard(c)


# ======================================================================
#  DURUM
# ======================================================================
def _durum():
    k = _D["kamera"]; ks = _D["komut"]; gb = _D["baglanti"]
    hd = _D["hedef"]; sv = _D["sunucu"]; dk = _D["dikey"]; by = _D["beyin"]
    d = {"t": round(time.time(), 2)}
    d["kamera"] = k.durum() if k else {"acik": False}
    if ks is not None:
        d["komut"] = dict(ks.durum)
        d["komut"]["kip"] = ks.kip
        d["komut"]["sayac"] = dict(ks.sayac)
    if gb is not None:
        d["arac"] = gb.saglik()
        try:
            x, y, z = gb.konum(); r, p, yw = gb.yonelim()
            vx, vy, vz = gb.hiz_vektoru()
            import math
            d["konum"] = {"kuzey": round(x, 1), "dogu": round(y, 1),
                          "yukari": round(z, 1)}
            d["durus"] = {"roll": round(math.degrees(r), 1),
                          "pitch": round(math.degrees(p), 1),
                          "yaw": round(math.degrees(yw), 1)}
            d["hiz"] = {"yatay": round(math.hypot(vx, vy), 1),
                        "dikey": round(vz, 1)}
            # ⭐ BURUN vs ROTA — yaw teşhisi (YALNIZ GÖSTERİM, güdüm okumaz).
            #   Araç düz ileri giderken fark ~0 olmalı. Değilse ya pusula
            #   bozuk ya da `attitude.yaw` aslında rota taşıyor; ikisi de
            #   dünya->gövde dönüşümünü bozar (bkz. baglanti.rota()).
            _rt = gb.rota() if hasattr(gb, "rota") else None
            if _rt is not None:
                _rd, _yh = _rt
                d["durus"]["rota"] = round(_rd, 1)
                d["durus"]["yer_hizi"] = round(_yh, 1)
                d["durus"]["burun_rota_fark"] = round(
                    (math.degrees(yw) - _rd + 180.0) % 360.0 - 180.0, 1)
        except Exception:
            pass
    if hd is not None:
        d["hedef"] = hd.durum()
        # ⭐ HEDEFİN YEREL KONUMU — YALNIZ 3B GÖRSELLEŞTİRME İÇİN.
        # ⛔ YARIŞMA KURALI (CLAUDE.md §10) İHLAL EDİLMİYOR: kural "görsel
        #   temas varken GPS ile GÜDÜM"ü yasaklar, GÖSTERİMİ değil. Bu
        #   değer `Beyin`e HİÇ girmez; doğrudan hedef kaynağından ve
        #   çerçeveden hesaplanır, güdüm yolundan geçmez.
        try:
            h = hd.son()
            if h and gb is not None and gb.cerceve.hazir:
                hx, hy, hz = gb.cerceve.metreye(
                    h["enlem"], h["boylam"], irtifa_yerden=h["irtifa_ev"])
                d["hedef_konum"] = {"kuzey": round(hx, 1), "dogu": round(hy, 1),
                                    "yukari": round(hz, 1)}
            # ⭐ HAM KONUM — BAYAT OLSA BİLE (2026-08-29). Operatör
            #   "paket geliyor ama verisi eski" durumunu görebilsin diye.
            #   3B ize GİRMEZ (hayalet iz çizmesin); yalnız METİN.
            hh = d["hedef"]
            if (hh.get("ham_enlem") is not None and gb is not None
                    and gb.cerceve.hazir):
                mx, my, mz = gb.cerceve.metreye(
                    hh["ham_enlem"], hh["ham_boylam"],
                    irtifa_yerden=hh.get("ham_irtifa") or 0.0)
                d["hedef_ham_konum"] = {
                    "kuzey": round(mx, 1), "dogu": round(my, 1),
                    "yukari": round(mz, 1),
                    "uzaklik": round((mx * mx + my * my) ** 0.5, 1)}
        except Exception:
            pass
    if ks is not None:
        # ⛔ GÜDÜMÜN İSTEĞİ — gönderilmiş olsun ya da olmasın. Yalnız
        #   gösterim; hakem bunu okumaz. Aracı OTONOM'a teslim etmeden
        #   "güdüm ne yapmak istiyor" sorusunu cevaplar.
        d["oto_cubuk"] = ks.otonom_istek
    if gb is not None and getattr(gb, "gnss_suzgec", None) is not None:
        d["gnss"] = gb.gnss_suzgec.durum()
    _vk = _D.get("video")
    if _vk is not None:
        d["video"] = _vk.durum()
    _in = _D.get("inis")
    if _in is not None:
        d["inis"] = _in.durum()
    if sv is not None:
        d["sunucu"] = sv.durum()
    if dk is not None:
        d["dikey"] = {"aktif": dk.aktif, "pasif": dk.n_pasif_cagri,
                      **{a: b for a, b in dk.tani.items()}}
    if by is not None:
        d["gudum"] = {"durum": getattr(by, "durum", "-"),
                      "faz": getattr(by, "faz", "-")}
    # ⭐ OPTİK SABİTLERİ ve MENZİL KAPILARI — panel menzili METRE olarak
    #   yazabilsin diye. ⛔ JS'e sabit YAZILMAZ: ayar env'den değişiyor
    #   (DOW_OPTIK_MENZIL_C) ve sabit yazmak paneli YALANCI yapar.
    try:
        from dow.gorus import kamera as _KAM
        from dow.gudum import ibvs as _IBV
        # ⛔ GÜDÜMLE AYNI ÖLÇÜ KULLANILMALI. `IbvsCfg.MENZIL_OLCU`
        #   "kosegen" ise menzil hypot(w,h) ve MENZIL_C_KOSEGEN ile
        #   hesaplanır; "max" ise max(w,h) ve MENZIL_C ile. Panel farklı
        #   ölçü kullanırsa ekranda yazan menzil, güdümün kapıda
        #   kullandığından FARKLI olur ve operatör yanlış teşhis koyar.
        _olcu = _IBV.IbvsCfg.MENZIL_OLCU
        d["optik"] = {
            "olcu": _olcu,
            "menzil_c": (_KAM.MENZIL_C_KOSEGEN if _olcu == "kosegen"
                         else _KAM.MENZIL_C),
            "menzil_min": _IBV.IbvsCfg.MENZIL_MIN_M,
            "menzil_max": _IBV.IbvsCfg.MENZIL_MAX_M,
            "boyut_min": _IBV.IbvsCfg.BOYUT_MIN_PX,
            "conf_min": _IBV.IbvsCfg.CONF_MIN,
            "f_px": _KAM.F_PX, "tilt": _KAM.TILT_DEG,
            "w": _KAM.IMG_W, "h": _KAM.IMG_H,
            # ⭐ MERCEK MODELİ — panelde görünsün ki "hangi modelle
            #   uçuyorum" sorusu ekrandan cevaplansın.
            "mercek": _KAM.OPTIK_MODEL}
    except Exception:
        pass
    d["gorsel_aktif"] = bool(_D.get("gorsel_aktif"))
    if _D.get("rtl") is not None:
        d["rtl"] = _D["rtl"].durum()
    if _D.get("kayit") is not None:
        d["kayit"] = _D["kayit"].durum()
    if _D["son_kutu"]:
        d["kutu"] = _D["son_kutu"]
    # ⭐ HAM TESPİT — modelin süzgeçsiz çıktısı. `_cizim()` bunu zaten
    #   VİDEONUN ÜSTÜNE çiziyordu ama durum sözlüğüne HİÇ girmiyordu:
    #   panelin menzil/sebep satırları ve UÇUŞ KAYDI boş kalıyordu.
    #   (30 Ağu 2026'da yakalandı — ekranda kutu var, kayıtta yok.)
    d["ham_kutu"] = _D.get("ham_kutu")
    d["ham_sebep"] = _D.get("ham_sebep") or ""
    if _D["olcut"] is not None:
        d["kilit"] = _D["olcut"]
    # Skydagger bağının kendi durumu (güvenli pencere, RC sayacı)
    if gb is not None and hasattr(gb.bag, "durum"):
        try:
            d["bag"] = gb.bag.durum()
        except Exception:
            pass
    # ⭐ ÖN UÇUŞ KONTROL LİSTESİ — EN SONDA hesaplanır, çünkü sözlüğün
    #   TAMAMINA bakar. ⛔ Hakemi (komut.py dört şart) DEĞİŞTİRMEZ; yalnız
    #   panelde OTONOM düğmesini kilitler. Arıza yönü güvenli: liste
    #   bozulursa otonom açılmaz, elle uçuşa düşülür.
    try:
        from gercek import kontrol_listesi as _KL
        d["kontrol"] = _KL.degerlendir(d)
    except Exception as e:
        d["kontrol"] = {"maddeler": [], "hazir": False,
                        "kalan": ["liste hatası: %s" % e]}
    return d


# ======================================================================
#  HTML
# ======================================================================
SAYFA = r"""<!doctype html><html lang=tr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>AVCI DRONE — YER KONTROL</title><style>
*{box-sizing:border-box;margin:0;padding:0}
/* ⛔ `html` DE BOYANIR: yalnız body boyanınca, sayfa içeriğinden uzun
   kaydırıldığında ya da bir öğe yüksekliği bozulduğunda tarayıcı BEYAZ
   gösteriyordu (sahada görüldü 2026-08-29). */
html{background:#0b0e13}
body{background:#0b0e13;color:#dfe6f0;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;
     min-height:100vh}
.ust{display:flex;gap:10px;align-items:center;padding:8px 12px;background:#131924;
     border-bottom:1px solid #223}
.ust b{font-size:15px;letter-spacing:1px}
.rozet{padding:3px 9px;border-radius:4px;font-weight:700;font-size:12px}
.ok{background:#123d1e;color:#5fe08a}.kotu{background:#3d1212;color:#ff7b7b}
.uyari{background:#3d3312;color:#ffd166}
main{display:grid;grid-template-columns:1fr 330px;gap:10px;padding:10px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.kutu{background:#131924;border:1px solid #223;border-radius:8px;padding:10px}
.kutu h3{font-size:11px;letter-spacing:1.5px;color:#7d8aa0;margin-bottom:7px;
         text-transform:uppercase}
/* ⛔ FPV KUTUSU SABİT ORANLI: kaynağı olmayan bir <img> tarayıcıya göre
   farklı yükseklik alır ve düzeni bozar (beyaz alan). Kap her zaman aynı
   yeri kaplar; görüntü içine oturur. */
.fpvkap{position:relative;width:100%;aspect-ratio:16/9;background:#000;
        border-radius:6px;overflow:hidden;display:flex;align-items:center;
        justify-content:center}
.fpvkap span{color:#7d8aa0;font-size:12px}
#fpv{width:100%;height:100%;object-fit:contain;display:none}
#fpv.var{display:block}
table{width:100%;border-collapse:collapse}
.pilcubuk{position:relative;height:16px;background:#0b0e13;border:1px solid #2a3550;
  border-radius:4px;overflow:hidden;margin-bottom:8px}
.pilcubuk i{display:block;height:100%;width:0;transition:width .3s}
.pilcubuk b{position:absolute;top:0;bottom:0;width:2px;background:#ff7b7b}
.katla{cursor:pointer;user-select:none}
.katla .ok3{color:#7d8aa0;font-size:10px}
.iyi{color:#5fe08a}.orta{color:#ffd166}.kotu2{color:#ff7b7b}
.klsat{display:flex;gap:8px;align-items:baseline;padding:3px 0;font-size:12px;
  border-bottom:1px solid #1c2438}
.klsat:last-child{border-bottom:0}
.klsat .im{width:14px;flex:none;font-weight:700}
.klsat .bas{flex:1}
.klsat .no{color:#7d8aa0;font-size:11px;text-align:right}
button.kucuk{padding:5px 6px;font-size:11px}
button.rtl{background:#3a2a0a;border-color:#ffd166;color:#ffd166}
button.rtl:hover{background:#4a360d}
button.rtl.aktif{background:#ffd166;color:#0b0e13}
td{padding:2px 0}td:last-child{text-align:right;font-weight:700}
.sonuk{color:#7d8aa0}
.kumanda{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px}
.pad{position:relative;aspect-ratio:1;background:#0b0e13;border:1px solid #2a3550;
     border-radius:10px;touch-action:none;overflow:hidden}
.pad .cizgi{position:absolute;background:#1c2438}
.pad .yatay{left:0;right:0;top:50%;height:1px}
.pad .dikey{top:0;bottom:0;left:50%;width:1px}
.topuz{position:absolute;width:26%;height:26%;border-radius:50%;
       background:#2f7dd1;border:2px solid #6fb2ff;transform:translate(-50%,-50%);
       left:50%;top:50%;pointer-events:none;transition:none}
.pad.kilitli .topuz{background:#556;border-color:#889}
.pad .kilit{position:absolute;inset:0;display:none;align-items:center;
            justify-content:center;text-align:center;font-size:11px;
            color:#ffd166;background:rgba(11,14,19,.72);padding:6px;
            line-height:1.35}
.pad.kilitli .kilit{display:flex}
.pad .etiket{position:absolute;bottom:4px;left:0;right:0;text-align:center;
             font-size:10px;color:#7d8aa0}
.dugmeler{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
button{flex:1;min-width:78px;padding:9px 6px;border:1px solid #2a3550;border-radius:6px;
       background:#1b2333;color:#dfe6f0;font:700 12px ui-monospace,monospace;cursor:pointer}
button:hover{background:#243049}
button.aktif{background:#1d4ed8;border-color:#60a5fa;color:#fff}
button.arm{background:#7f1d1d;border-color:#ef4444}
/* ⛔ ACİL İNİŞ — kasten BÜYÜK, kasten AYRI SATIRDA, kasten farklı renk.
   Yanına başka düğme konmaz: panik anında yanlış düğmeye basmak
   düğmenin varlık sebebini yok eder. */
/* son çare — kasten KÜÇÜK ve sönük: birincil yol dikey iniştir. */
button.kucukacil{background:#3f1414;border-color:#7f1d1d;color:#fca5a5;
  font-size:10px;padding:5px;width:100%;letter-spacing:0}
button.kucukacil:hover{background:#5b1a1a}
button.kucukacil.aktif{background:#7f1d1d;color:#fff;border-color:#ef4444}
/* görsel güdüm izni — mor: ne acil (kırmızı) ne normal (mavi) */
button.video{background:#312e81;border-color:#818cf8;color:#e0e7ff;
  font-weight:600;padding:9px;width:100%}
button.video:hover{background:#3730a3}
button.video.kayitta{background:#7f1d1d;border-color:#f87171;color:#fee2e2;
  animation:videoyanip 1.4s steps(2,end) infinite}
@keyframes videoyanip{50%{background:#991b1b}}
button.gorev{background:#065f46;border-color:#34d399;color:#d1fae5;
  font-weight:700;padding:13px;width:100%;font-size:14px;letter-spacing:.4px}
button.gorev:hover{background:#047857}
button.gorev.aktif{background:#064e3b;border-color:#6ee7b7}
button.gorev:disabled{background:#1f2937;border-color:#374151;color:#6b7280;
  cursor:not-allowed}
button.acil{background:#b91c1c;border-color:#fca5a5;color:#fff;
  font-weight:700;letter-spacing:.5px;padding:12px;width:100%;font-size:14px}
button.acil:hover{background:#dc2626}
button.acil.aktif{background:#450a0a;border-color:#f87171;
  animation:acilyanip 1s steps(2,end) infinite}
@keyframes acilyanip{50%{background:#7f1d1d}}
button.armli{background:#166534;border-color:#4ade80}
.uyarilar{margin-top:8px;font-size:11px;color:#ffd166;min-height:16px}
#uc3b{width:100%;height:260px;display:block;background:#080b10;border-radius:6px;
      cursor:grab;touch-action:none}
#uc3b:active{cursor:grabbing}
.uc3bbilgi{display:flex;gap:12px;margin-top:6px;font-size:11px}
</style></head><body>
<div class=ust>
  <b>AVCI DRONE — YER KONTROL</b>
  <span id=r_link class="rozet kotu">LINK</span>
  <span id=r_gps  class="rozet kotu">GPS</span>
  <span id=r_kip  class="rozet uyari">MANUEL</span>
  <span id=r_insan class="rozet uyari">girdi: —</span>
  <span id=r_arm  class="rozet kotu">DISARM</span>
  <span id=r_inis class="rozet" hidden>⛔ İNİŞ — PAKET KESİLDİ</span>
  <span id=r_sunucu class="rozet kotu">SUNUCU</span>
  <span style="flex:1"></span>
  <span id=r_saat class=sonuk></span>
</div>
<main>
  <div class=kutu>
    <h3>FPV</h3>
    <div class=fpvkap><span id=fpvyok>kamera bekleniyor…</span>
      <img id=fpv alt=""></div>
  </div>
  <div>
    <div class=kutu>
      <h3>Manuel kumanda</h3>
      <div class=kumanda>
        <div class=pad id=padL><div class="cizgi yatay"></div><div class="cizgi dikey"></div>
          <div class=topuz id=topuzL></div><div class=kilit>KUMANDA SÜRÜYOR<br>pilot çubuğu bıraksın,<br>3 s sonra panel geri alır</div>
          <div class=etiket>GAZ / DÖNÜŞ</div></div>
        <div class=pad id=padR><div class="cizgi yatay"></div><div class="cizgi dikey"></div>
          <div class=topuz id=topuzR></div><div class=kilit>KUMANDA SÜRÜYOR<br>pilot çubuğu bıraksın,<br>3 s sonra panel geri alır</div>
          <div class=etiket>İLERİ / YANAL</div></div>
      </div>
      <div class=dugmeler>
        <button id=b_manuel class=aktif>MANUEL</button>
        <button id=b_otonom>OTONOM</button>
        <button id=b_rtl class=rtl>RTL — EVE DÖN</button>
        <button id=b_arm class=arm>ARM (BASILI TUT)</button>
      </div>
      <div class=dugmeler style="margin-top:8px">
        <button id=b_gorev class=gorev>🚀 GÖREVİ BAŞLAT (OTONOM KALKIŞ)</button>
      </div>
      <div class=dugmeler style="margin-top:6px">
        <button id=b_inis class=acil>⛔ FAILSAFE — DİKEY İNİŞ</button>
      </div>
      <div class=dugmeler style="margin-top:2px">
        <button id=b_kes class=kucukacil>son çare: RC paketini kes
          (kartın kendi AUTO-LAND'i)</button>
      </div>
      <div class=dugmeler style="margin-top:6px">
        <button id=b_video class=video>⏺ VİDEO KAYDI BAŞLAT</button>
      </div>
      <div class=dugmeler>
        <button id=b_koken>KÖKEN KUR</button>
        <button id=b_kmd>KUMANDAYI YOK SAY</button>
        <span id=r_safe class="rozet uyari" style="flex:1;text-align:center">—</span>
      </div>
      <div class=uyarilar id=uyarilar></div>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3 class=katla id=kl_bas>Ön uçuş kontrolü <span id=kl_ozet
        class=rozet>—</span> <span class=ok3 id=kl_ok>▾</span></h3>
      <div id=kl_liste></div>
      <div class=satir style="margin-top:8px">
        <button id=b_kayit class=kucuk>KAYDI GÖSTER</button>
      </div>
      <div id=kl_kayit class=sonuk style="font-size:11px;margin-top:6px"></div>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Pil <span class=sonuk style="text-transform:none"
        id=pil_ozet>—</span></h3>
      <div class=pilcubuk><i id=pil_dolu></i><b id=pil_esik></b></div>
      <table id=pil_tablo></table>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Uçuş</h3>
      <table id=telem_ucus></table>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Hedef</h3>
      <table id=telem_hedef></table>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3 class=katla id=sistem_bas>Sistem <span class=ok3>▸</span></h3>
      <table id=telem_sistem style="display:none"></table>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>3B Konum <span class=sonuk style="text-transform:none">
        · sürükle=döndür · tekerlek=yakınlaş · çift tık=sıfırla</span></h3>
      <canvas id=uc3b></canvas>
      <div class=uc3bbilgi>
        <span style="color:#6fb2ff">● drone</span>
        <span style="color:#ff9f43">● hedef</span>
        <span id=uc3bmesafe class=sonuk></span>
      </div>
    </div>
  </div>
</main>
<script>
// ⛔ JS HATALARI SESSİZ KALMASIN. Bir istisna, durum döngüsünü ya da
//   çubuk olaylarını sessizce öldürebilir; operatör bunu "donma" sanar.
//   Artık ekranda yazar ve konsola düşer.
let jsHata="";
window.addEventListener("error",e=>{ jsHata="JS: "+(e.message||"hata"); });
window.addEventListener("unhandledrejection",e=>{
  jsHata="JS(promise): "+((e.reason&&e.reason.message)||e.reason||"hata"); });
let S={thr:0,yaw:0,pitch:0,roll:0,arm:false,izin:false};
let kumandaVar=false, armBasili=false, kmdYokSay=false;
// ⛔ PANEL BEKÇİSİ: POST'lar gerçekten gidiyor mu? Donma SESSİZ olmamalı —
//   operatör "arayüz dondu mu, kumanda mı devraldı" diye tahmin etmemeli.
// ⛔⛔ `post` — PANELDEKİ TÜM DÜĞMELERİN ORTAK YOLU.
//   YAŞANDI (2026-08-31, sahada): RTL, dikey iniş, paket kes, görsel izin
//   ve görevi başlat düğmelerinin hepsi `post(...)` çağırıyordu ama bu
//   fonksiyon HİÇ TANIMLI DEĞİLDİ. Tarayıcı "post is not defined" atıyor,
//   düğme sessizce hiçbir şey yapmıyordu. Failsafe'i Python'dan doğrudan
//   HTTP ile sınadığım için testlerde görünmedi — düğme yolu HİÇ
//   denenmemişti. Bekçi R126 artık bunu kilitliyor.
//   `function` ile tanımlı (hoisting): yukarıdaki handler'lar da görsün.
async function post(yol, govde){
  const y = await fetch(yol, {method:"POST",
                             body: JSON.stringify(govde||{})});
  try{ return await y.json(); }catch(_){ return {ok: y.ok ? 1 : 0}; }
}
let sonBasarili=Date.now(), ucusta=0, postHata=0;
// ⛔ SEKME GÖRÜNÜRLÜK KONTROLÜ KALDIRILDI (kullanıcı kararı 2026-08-29):
//   "sekme arka plana düşünce o zamanlayıcıyı kısmayı falan kaldır, o
//    nasıl şey öyle niye donduruyor kontrolü sil onu".
//   Panel artık sekme gizlenince NE uyarı basar NE de çubuğu bırakır.
//   ⚠ Chrome'un kendi kısıtlaması yazılımla kapatılamaz; onun yerine
//     hakemin panel zaman aşımı 0.5 -> 1.5 s'e çıkarıldı, böylece kısa
//     kısıtlamalar paketi kesmez. Gerçek hız aşağıda "panel→sunucu"
//     satırında GÖRÜNÜR — uyarı değil, bilgi.
let postHz=0, postSay=0;
setInterval(()=>{ postHz=postSay; postSay=0; },1000);

function pad(el,topuz,eksenX,eksenY,merkezleY){
  // ⛔ AKTİF İŞARETÇİ KİMLİKLE TAKİP EDİLİR.
  //   Eski hâlde sadece bir `aktif` bayrağı vardı ve `pointerleave` de onu
  //   düşürüyordu. `setPointerCapture` ile sürüklerken sınır olayları
  //   tarayıcıdan tarayıcıya farklı davranır; işaretçi kimliği yakalanınca
  //   bu belirsizlik tamamen kalkar: yalnız BİZİM yakaladığımız işaretçinin
  //   up/cancel'ı çubuğu bırakır.
  let aktifId=null;
  const yerlestir=(x,y)=>{ topuz.style.left=(50+x*50)+"%"; topuz.style.top=(50-y*50)+"%"; };
  const oku=(ev)=>{
    const r=el.getBoundingClientRect();
    let x=((ev.clientX-r.left)/r.width)*2-1;
    let y=-(((ev.clientY-r.top)/r.height)*2-1);
    x=Math.max(-1,Math.min(1,x)); y=Math.max(-1,Math.min(1,y));
    S[eksenX]=x; S[eksenY]=y; yerlestir(x,y);
  };
  el.addEventListener("pointerdown",e=>{
    if(kumandaVar) return;
    aktifId=e.pointerId;
    try{ el.setPointerCapture(e.pointerId); }catch(_){}
    oku(e); e.preventDefault();
  });
  el.addEventListener("pointermove",e=>{ if(e.pointerId===aktifId) oku(e); });
  const birak=(e)=>{
    if(aktifId===null || (e && e.pointerId!==aktifId)) return;
    try{ el.releasePointerCapture(aktifId); }catch(_){}
    aktifId=null;
    S[eksenX]=0; if(merkezleY) S[eksenY]=0;
    yerlestir(S[eksenX],S[eksenY]);
  };
  el.addEventListener("pointerup",birak);
  el.addEventListener("pointercancel",birak);
  // ⛔ FARE TUŞU BASILIYKEN PENCERE DEĞİŞİRSE `pointerup` HİÇ GELMEZ ve
  //   çubuk takılı kalırdı. `blur` bunu kapatır.
  //   ⚠ `visibilitychange` KASTEN YOK (kullanıcı kararı): sekme arka plana
  //     düşünce çubuk BIRAKILMAZ.
  window.addEventListener("blur",()=>birak(null));
  return yerlestir;
}
// SOL: X=dönüş(merkeze döner), Y=gaz(MERKEZE DÖNMEZ — gaz çubuğu öyledir)
const yerL=pad(document.getElementById("padL"),document.getElementById("topuzL"),"yaw","thr",false);
// SAĞ: ikisi de merkeze döner
const yerR=pad(document.getElementById("padR"),document.getElementById("topuzR"),"roll","pitch",true);

document.getElementById("b_manuel").onclick=()=>kip("MANUEL");
// ⛔⛔ DÜĞME ARTIK ÖLMÜYOR (2026-09-01 — SAHADA YAŞANDI).
//   ESKİ HÂLİ: ön uçuş listesi eksikken `bOto.disabled=true` idi.
//   Tıklamak HİÇBİR ŞEY yapmıyordu: ne hareket, ne uyarı, ne sebep.
//   Operatör yarışma sırasında düğmeye bastı, hiçbir şey olmadı ve
//   niye olmadığını göremedi. Kaçış yolu (çift tıkla zorla) hiçbir
//   yerde YAZMIYORDU — keşfedilmesi imkânsızdı.
//   YENİ HÂLİ: düğme HER ZAMAN tıklanabilir; eksik varsa hangi
//   maddelerin eksik olduğunu SAYARAK onay ister. Kaza koruması
//   duruyor (tek tıkla otonoma geçilemez) ama artık GÖRÜNÜR.
//   ⛔ HAKEM DEĞİŞMEDİ: `komut.py`'deki dört şart yerinde. Bu düğme
//     yalnız panelin kip SEÇİMİDİR; otonomun gerçekten açılıp
//     açılmayacağına hakem karar verir (R39/R108).
document.getElementById("b_otonom").onclick=()=>{
  const kls=(window._sonDurum||{}).kontrol||{};
  const eksik=kls.kalan_metin||kls.kalan||[];
  if(eksik.length && !window._klZorla){
    if(!confirm("ÖN UÇUŞ KONTROLÜ EKSİK — "+eksik.length+" madde:\n\n  · "+
                eksik.join("\n  · ")+
                "\n\nYine de OTONOM açılsın mı?\n"+
                "(bu karar uçuş kaydına düşer)")) return;
    window._klZorla=true;
  }
  kip("OTONOM");
};
// ⏺ VİDEO KAYDI — FPV görüntüsünü dosyaya yazar.
//   Yarışma kilitlenmeleri kaydedilen videolarla inceliyor (doküman §8);
//   uçuş sonrası analizde de görüntü ile log birbirini doğrular.
document.getElementById("b_video").onclick=async()=>{
  const kayitta=document.getElementById("b_video").classList.contains("kayitta");
  const r=await post("/api/video",{ac:!kayitta});
  if(!r.ok) alert("video kaydı: "+(r.sebep||"başlatılamadı"));
};
// 🚀 GÖREVİ BAŞLAT — otonom kalkış + takip.
//   ⛔ ARM'ı BU DÜĞME YAPMAZ. Arm daima insandan gelir (bekçi R35);
//     güdümün arm kanalına erişimi YOKTUR ki bir yazılım hatası aracı
//     arm edemesin. Uçuş için arm KUMANDANIN anahtarından gelir —
//     paneldeki ARM basılı tutma ister, uçuş boyunca tutulamaz.
document.getElementById("b_gorev").onclick=async()=>{
  const d=window._sonDurum||{};
  const k=d.komut||{};
  if(!k.arm){
    alert("⛔ ARAÇ ARM DEĞİL.\n\nÖnce KUMANDANIN arm anahtarını aç "+
          "(panel düğmesi basılı tutma ister, uçuşta kullanılmaz).");
    return;
  }
  if(!confirm("🚀 GÖREVİ BAŞLAT\n\nAraç KENDİ KALKACAK:\n"+
              "  · dikey tırmanış 3 m/s ile 40 m'ye\n"+
              "  · sonra hedefe yönelip GPS ile takip\n\n"+
              "⛔ Pervanelerin takılı ve alanın boş olduğunu doğrula.\n"+
              "⛔ Kumanda elinde olsun — çubuğa dokunmak otonomu keser.\n\n"+
              "Başlasın mı?")) return;
  await post("/api/kip",{kip:"OTONOM"});
};
// ⛔⛔ FAILSAFE = DİKEY İNİŞ (kullanıcı kararı 2026-08-31).
//   Nerede olursak olalım — güdüm sürerken de, pilot elle uçarken de —
//   bu düğme görevi keser ve uçuş kartının ALT HOLD + POS HOLD kipleriyle
//   olduğu yerde aşağı iner.
//   ONAY SORMAZ: acil durumda bir tık daha istemek düğmenin varlık
//   sebebini yok eder. Yanlışlıkla basmaya karşı korumamız KONUM ve
//   GÖRÜNÜM (kendi satırı, büyük, kırmızı).
document.getElementById("b_inis").onclick=async()=>{
  const acik=document.getElementById("b_inis").classList.contains("aktif");
  if(acik){
    if(!confirm("DİKEY İNİŞ DURDURULSUN MU?\n\n"+
                "Araç alçalmayı bırakır, ALT HOLD / POS HOLD kapanır\n"+
                "ve kontrol sana döner. Emin misin?")) return;
    await post("/api/dikey_inis",{ac:false}); return;
  }
  const r=await post("/api/dikey_inis",{ac:true});
  if(!r.ok) alert("iniş başlamadı: "+(r.sebep||"?"));
};
// ⛔ SON ÇARE — RC paketini komple kes. Dikey iniş uçuş kartının
//   kiplerine güvenir; o kipler beklendiği gibi davranmazsa (ör. araç
//   alçalacağına tırmanıyorsa) bu düğme bizi devreden tamamen çıkarır
//   ve kartın KENDİ failsafe AUTO-LAND'ine bırakır.
//   Kasten KÜÇÜK: birincil acil yol dikey iniştir.
document.getElementById("b_kes").onclick=async()=>{
  const acik=document.getElementById("b_kes").classList.contains("aktif");
  if(acik){
    if(!confirm("PAKET KESME KALDIRILSIN MI?\n\n"+
                "⚠ Bu aracı kurtarmaz: uçuş kartı failsafe'ten çıkmayabilir.\n"+
                "Yine de kaldırılsın mı?")) return;
    await post("/api/inis",{ac:false}); return;
  }
  await post("/api/inis",{ac:true});
};
// ⛔ RTL ONAY İSTER: aracı otonom olarak eve uçurur. Yanlışlıkla
//   basılırsa uçak elinden çıkar.
document.getElementById("b_rtl").onclick=async()=>{
  const acik=document.getElementById("b_rtl").classList.contains("aktif");
  if(acik){ await post("/api/rtl",{ac:false}); return; }
  if(!confirm("RTL — EVE DÖN\n\nAraç GPS ile KALKIŞ NOKTASINA dönecek,\n"+
              "önce güvenli irtifaya tırmanacak ve orada ASILI kalacak.\n"+
              "Kendiliğinden İNMEZ.\n\nBaşlasın mı?"))return;
  const r=await post("/api/rtl",{ac:true});
  if(!r.ok) alert("RTL başlamadı: "+(r.sebep||"?"));
};
// ⛔ ZORLAMA YOLU AÇIK. Sahada listenin bir maddesi yanlış kırmızı
//   yanabilir; operatörün otonomdan MAHRUM kalması bundan tehlikelidir.
//   Çift tık + onay ile kilit kalkar ve durum kayda düşer.
document.getElementById("b_otonom").ondblclick=()=>{
  if(window._klZorla) return;
  if(confirm("ÖN UÇUŞ KONTROLÜ EKSİK.\n\nYine de OTONOM açılsın mı?\n"+
             "Bu karar uçuş kaydına düşer.")){
    window._klZorla=true;
    document.getElementById("b_otonom").disabled=false;
  }
};
document.getElementById("kl_bas").onclick=()=>{
  const t=document.getElementById("kl_liste");
  const ac=(t.style.display==="none");
  t.style.display=ac?"":"none";
  document.getElementById("kl_ok").textContent=ac?"▾":"▸";
};
document.getElementById("b_kayit").onclick=async()=>{
  const e=document.getElementById("kl_kayit");
  try{
    const d=await (await fetch("/api/durum")).json();
    e.textContent=(d.kayit&&d.kayit.yol)?d.kayit.yol:"kayıt kapalı";
  }catch(x){ e.textContent="okunamadı"; }
};
function kip(k){
  // ⛔ ÖNCE WS: HTTP kuyruğa girip GECİKEBİLİR (sahada tam bu oldu —
  //   MANUEL'e basıldı, düğme maviye döndü ama kip OTONOM kaldı).
  if(!wsGonder({c:"kip",kip:k}))
    fetch("/api/kip",{method:"POST",body:JSON.stringify({kip:k})}).catch(()=>{});
  document.getElementById("b_manuel").classList.toggle("aktif",k=="MANUEL");
  document.getElementById("b_otonom").classList.toggle("aktif",k=="OTONOM");
  S.izin=(k=="OTONOM"); }
// ⭐ YEREL KÖKEN — kalkıştan ÖNCE, araç YERDEYKEN basılır.
//    Bütün GPS koordinatları buna göre metreye çevrilir; uçuş ortasında
//    değiştirmek güdümün altındaki zemini kaydırmak demektir.
document.getElementById("b_koken").onclick=async()=>{
  const r=await (await fetch("/api/koken",{method:"POST",body:"{}"}).catch(
      ()=>({json:()=>({ok:false,mesaj:"istek gitmedi"})}))).json();
  document.getElementById("uyarilar").textContent=r.mesaj||"";
  if(!r.ok && confirm(r.mesaj+"\n\nYine de ZORLA kurulsun mu? (zayıf fix "+
     "bütün uçuşu kaydırır)")){
    const z=await (await fetch("/api/koken",{method:"POST",
      body:JSON.stringify({zorla:true})})).json();
    document.getElementById("uyarilar").textContent=z.mesaj||"";
  }};
document.getElementById("b_kmd").onclick=(e)=>{
  kmdYokSay=!kmdYokSay;
  e.target.classList.toggle("aktif",kmdYokSay);
  e.target.textContent=kmdYokSay?"KUMANDA YOK SAYILIYOR":"KUMANDAYI YOK SAY";
};
// ⛔ ARM BASILI TUTMA İSTER — tek tıkla yanlışlıkla arm edilemesin
const bArm=document.getElementById("b_arm");
bArm.addEventListener("pointerdown",()=>{armBasili=true;S.arm=true;});
const armBirak=()=>{armBasili=false;S.arm=false;};
bArm.addEventListener("pointerup",armBirak);
bArm.addEventListener("pointerleave",armBirak);
bArm.addEventListener("pointercancel",armBirak);

// ⛔ ESKİ HÂLİ setInterval(...,33) İDİ VE GERİ BASINÇ YOKTU: önceki istek
//   bitmeden yenisi ateşleniyordu. Tarayıcının bağlantı havuzu (kaynak
//   başına ~6) MJPEG akışıyla birlikte dolduğunda istekler kuyruğa
//   yığılıyor ve arayüz tıkanıyor. Şimdi: bir seferde EN FAZLA BİR istek.
// ======================================================================
//  WEBSOCKET — ANA KANAL
// ======================================================================
// ⛔ NİYE: panelin üç HTTP akışı (30 Hz çubuk, 5 Hz durum, 15 Hz kare)
//   Chrome'un kaynak başına 6 bağlantısını doldurup istekleri KUYRUĞA
//   alıyordu; kuyruk büyüyünce arayüz tepkisiz kalıyor ve DÜĞME
//   TIKLAMALARI BİLE GEÇMİYORDU. Sunucu bu sırada kip değişikliğini
//   0.5 ms'de işliyordu — sorun hiçbir zaman sunucuda değildi.
//   Tek WebSocket bunu kökünden kaldırır: kuyruk yok, istek yükü yok.
// ⛔ HTTP YOLU YEDEK OLARAK DURUYOR: WS kurulamazsa kendiliğinden ona
//   düşülür. Tek yol bırakmak yeni bir tek arıza noktası olurdu.
let ws=null, wsAcik=false;
function wsBagla(){
  try{
    ws = new WebSocket((location.protocol==="https:"?"wss://":"ws://")
                        + location.host + "/ws");
  }catch(e){ setTimeout(wsBagla,1000); return; }
  ws.onopen   = ()=>{ wsAcik=true; postHata=0; };
  ws.onmessage= (e)=>{ sonBasarili=Date.now(); postSay++;
                       try{ gosterim(JSON.parse(e.data)); }
                       catch(err){ jsHata="JS(durum): "+(err&&err.message||err); } };
  ws.onclose  = ()=>{ wsAcik=false; ws=null; setTimeout(wsBagla,800); };
  ws.onerror  = ()=>{ try{ws.close();}catch(_){} };
}
wsBagla();
function wsGonder(o){
  if(ws && wsAcik && ws.readyState===1){
    try{ ws.send(JSON.stringify(o)); return true; }catch(e){}
  }
  return false;
}

// --- ÇUBUK GÖNDERİMİ: WS varsa oradan, yoksa HTTP yedeği ---
function manuelGonder(){
  if(wsGonder(Object.assign({c:"cubuk"}, S))){
    setTimeout(manuelGonder,33); return;
  }
  if(ucusta>0){ setTimeout(manuelGonder,10); return; }
  ucusta++;
  // ⛔ ZAMAN AŞIMI ŞART: zaman aşımsız bir fetch SONSUZA KADAR asılı
  //   kalabilir; `ucusta` bir daha düşmez ve komut akışı KALICI durur.
  const iptal=new AbortController();
  const zam=setTimeout(()=>iptal.abort(),800);
  fetch("/api/manuel",{method:"POST",body:JSON.stringify(S),signal:iptal.signal})
    .then(r=>{ sonBasarili=Date.now(); postHata=0; postSay++; })
    .catch(e=>{ postHata++; })
    .finally(()=>{ clearTimeout(zam); ucusta--; setTimeout(manuelGonder,33); });
}
manuelGonder();

// ⛔ FPV: MJPEG YERİNE PERİYODİK TEK KARE.
//   Kalıcı MJPEG bağlantısı tarayıcının bağlantı havuzunu (kaynak başına 6)
//   sürekli meşgul ediyordu ve sayfa donuyordu. Tek kare her seferinde
//   bağlantıyı bırakır. Ayrıca ÖNCEKİ KARE BİTMEDEN yenisi istenmez —
//   yavaş bir kare, komut akışını asla geciktiremez.
let kameraVar=false, kareUcusta=false, kareHz=0, kareSay=0;
const fpvImg=document.getElementById("fpv"), fpvYok=document.getElementById("fpvyok");
function kareAl(){
  if(!kameraVar || kareUcusta || document.hidden){ setTimeout(kareAl,200); return; }
  kareUcusta=true;
  const im=new Image();
  im.onload=()=>{ fpvImg.src=im.src; fpvImg.classList.add("var");
                  fpvYok.style.display="none"; kareSay++;
                  kareUcusta=false; setTimeout(kareAl,66); };   // ~15 Hz
  im.onerror=()=>{ kareUcusta=false; setTimeout(kareAl,500); };
  im.src="/kare.jpg?t="+Date.now();
}
kareAl();
setInterval(()=>{ kareHz=kareSay; kareSay=0; },1000);

// ======================================================================
//  3B KONUM GÖRÜNÜMÜ — drone ve hedef, döndürülebilir
// ======================================================================
// ⛔ HARİCİ KÜTÜPHANE YOK. Panel sahada İNTERNETSİZ çalışır; CDN'den
//   three.js çekmek orada sessizce başarısız olurdu. Nokta bulutu +
//   yörünge kamerası için gereken matematik zaten birkaç satır.
//
// ÇERÇEVE: x=KUZEY, y=DOĞU, z=YUKARI (gercek/arayuz.py sözleşmesi).
// Yansıtma: önce yatay dönüş (azimut), sonra yükseliş, sonra zayıf
// perspektif. Derinlik `d`, uzaktaki noktayı küçültmek için kullanılır.
const C3 = {az:-0.6, el:0.45, olcek:1.0, sur:false, sx:0, sy:0,
            droneIz:[], hedefIz:[], IZ_MAX:400};
const c3 = document.getElementById("uc3b");
const g3 = c3.getContext("2d");

function c3boyut(){
  const r=c3.getBoundingClientRect();
  const o=window.devicePixelRatio||1;
  c3.width=Math.max(1,Math.round(r.width*o));
  c3.height=Math.max(1,Math.round(r.height*o));
  g3.setTransform(o,0,0,o,0,0);
  return [r.width, r.height];
}
c3.addEventListener("pointerdown",e=>{C3.sur=true;C3.sx=e.clientX;C3.sy=e.clientY;
  try{c3.setPointerCapture(e.pointerId);}catch(_){}});
c3.addEventListener("pointermove",e=>{ if(!C3.sur)return;
  C3.az += (e.clientX-C3.sx)*0.01;
  C3.el = Math.max(-1.45, Math.min(1.45, C3.el + (e.clientY-C3.sy)*0.01));
  C3.sx=e.clientX; C3.sy=e.clientY; });
const c3birak=()=>{C3.sur=false;};
c3.addEventListener("pointerup",c3birak);
c3.addEventListener("pointercancel",c3birak);
window.addEventListener("blur",c3birak);
c3.addEventListener("wheel",e=>{ e.preventDefault();
  C3.olcek *= (e.deltaY>0? 0.9 : 1.1);
  C3.olcek = Math.max(0.15, Math.min(8, C3.olcek)); }, {passive:false});
c3.addEventListener("dblclick",()=>{ C3.az=-0.6; C3.el=0.45; C3.olcek=1.0; });

function c3ciz(){
  const [W,H]=c3boyut();
  g3.clearRect(0,0,W,H);
  const cx=W/2, cy=H/2+20;
  const noktalar=C3.droneIz.concat(C3.hedefIz);
  // otomatik ölçek: bütün noktalar sığsın (en az 20 m yarıçap)
  let r=20;
  for(const p of noktalar) r=Math.max(r,Math.abs(p[0]),Math.abs(p[1]),Math.abs(p[2]));
  const K=(Math.min(W,H)*0.38/r)*C3.olcek;
  const ca=Math.cos(C3.az), sa=Math.sin(C3.az);
  const ce=Math.cos(C3.el), se=Math.sin(C3.el);
  const yans=(x,y,z)=>{
    const x1= x*ca + y*sa;
    const y1=-x*sa + y*ca;
    const d = y1*ce + z*se;               // derinlik
    const u = -y1*se + z*ce;              // ekran yukarı
    const k = 900/(900+d*K*0.5);          // zayıf perspektif
    return [cx + x1*K*k, cy - u*K*k, d];
  };
  // --- zemin ızgarası ---
  const adim=Math.pow(10,Math.round(Math.log10(r/3)));
  g3.strokeStyle="#18202e"; g3.lineWidth=1; g3.beginPath();
  for(let i=-3;i<=3;i++){
    let a=yans(i*adim,-3*adim,0), b=yans(i*adim,3*adim,0);
    g3.moveTo(a[0],a[1]); g3.lineTo(b[0],b[1]);
    a=yans(-3*adim,i*adim,0); b=yans(3*adim,i*adim,0);
    g3.moveTo(a[0],a[1]); g3.lineTo(b[0],b[1]);
  }
  g3.stroke();
  // --- eksenler ---
  const eks=[[3*adim,0,0,"#3d5a80","K"],[0,3*adim,0,"#3d8055","D"],[0,0,2*adim,"#805a3d","↑"]];
  for(const [x,y,z,renk,et] of eks){
    const o=yans(0,0,0), p=yans(x,y,z);
    g3.strokeStyle=renk; g3.lineWidth=1.5;
    g3.beginPath(); g3.moveTo(o[0],o[1]); g3.lineTo(p[0],p[1]); g3.stroke();
    g3.fillStyle=renk; g3.font="11px monospace"; g3.fillText(et,p[0]+4,p[1]);
  }
  // --- izler ---
  const izCiz=(iz,renk)=>{
    if(iz.length<2) return;
    g3.strokeStyle=renk; g3.lineWidth=1.2; g3.globalAlpha=0.55; g3.beginPath();
    let ilk=true;
    for(const p of iz){ const q=yans(p[0],p[1],p[2]);
      if(ilk){g3.moveTo(q[0],q[1]);ilk=false;} else g3.lineTo(q[0],q[1]); }
    g3.stroke(); g3.globalAlpha=1;
  };
  izCiz(C3.droneIz,"#2f7dd1"); izCiz(C3.hedefIz,"#c77a20");
  // --- noktalar + aralarındaki çizgi ---
  const son=(iz)=>iz.length?iz[iz.length-1]:null;
  const dP=son(C3.droneIz), hP=son(C3.hedefIz);
  if(dP&&hP){
    const a=yans(...dP), b=yans(...hP);
    g3.strokeStyle="#3a4a63"; g3.setLineDash([4,4]);
    g3.beginPath(); g3.moveTo(a[0],a[1]); g3.lineTo(b[0],b[1]); g3.stroke();
    g3.setLineDash([]);
  }
  const noktaCiz=(p,renk,ad)=>{
    if(!p) return;
    const q=yans(p[0],p[1],p[2]);
    // yerden dikey çizgi (yükseklik hissi)
    const t=yans(p[0],p[1],0);
    g3.strokeStyle=renk; g3.globalAlpha=0.35; g3.beginPath();
    g3.moveTo(q[0],q[1]); g3.lineTo(t[0],t[1]); g3.stroke(); g3.globalAlpha=1;
    g3.fillStyle=renk; g3.beginPath(); g3.arc(q[0],q[1],5,0,6.284); g3.fill();
    g3.fillStyle="#dfe6f0"; g3.font="10px monospace";
    g3.fillText(ad+"  "+p[2].toFixed(0)+"m", q[0]+8, q[1]-6);
  };
  noktaCiz(hP,"#ff9f43","hedef");
  noktaCiz(dP,"#6fb2ff","drone");
  if(dP&&hP){
    const m=Math.hypot(dP[0]-hP[0],dP[1]-hP[1],dP[2]-hP[2]);
    document.getElementById("uc3bmesafe").textContent="mesafe "+m.toFixed(0)+" m";
  }
}
function c3ekle(iz,p){
  const s=iz[iz.length-1];
  if(!s || Math.abs(s[0]-p[0])>0.3 || Math.abs(s[1]-p[1])>0.3
        || Math.abs(s[2]-p[2])>0.3){
    iz.push(p); if(iz.length>C3.IZ_MAX) iz.shift();
  } else { iz[iz.length-1]=p; }
}
setInterval(c3ciz, 100);

// SİSTEM bloğu katlanabilir — uçuşta gerekmeyen sayaçlar göz yormasın.
// Varsayılan KAPALI; tıklayınca açılır.
document.getElementById("sistem_bas").onclick=()=>{
  const t=document.getElementById("telem_sistem");
  const ac=(t.style.display==="none");
  t.style.display=ac?"":"none";
  document.querySelector("#sistem_bas .ok3").textContent=ac?"▾":"▸";
};

const sat=(a,b,s)=>`<tr><td class=sonuk>${a}</td><td class="${s||''}">${b}</td></tr>`;
function rozet(id,ok,metin){ const e=document.getElementById(id);
  e.className="rozet "+(ok===true?"ok":ok===false?"kotu":"uyari"); e.textContent=metin; }
// HTTP YEDEK durum döngüsü — YALNIZ WebSocket yokken koşar.
let durumUcusta=false;
setInterval(async()=>{
  if(wsAcik) return;                    // WS varken HTTP'ye HİÇ gidilmez
  if(durumUcusta) return;               // geri basınç: kuyruk yığılmasın
  durumUcusta=true;
  const iptal=new AbortController();
  const zam=setTimeout(()=>iptal.abort(),1500);
  let d;
  try{ d=await (await fetch("/api/durum",{signal:iptal.signal})).json(); }
  catch(e){ clearTimeout(zam); durumUcusta=false; return; }
  clearTimeout(zam); durumUcusta=false;
  sonBasarili=Date.now(); postSay++;
  gosterim(d);
},200);

// ⛔ GÖSTERİM TEK FONKSİYONDA: hem WS hem HTTP yolu AYNI kodu çağırır.
//   İki kopya tutmak, birinde düzeltilen hatanın öbüründe kalması demektir.
function gosterim(d){
  // ⛔ TÜM GÖSTERİM İŞİ TRY İÇİNDE: burada atılan bir istisna her tikte
  //   tekrarlanır ve arayüz "donmuş" görünür. Hata ekrana yazılır.
  try{
  const a=d.arac||{}, k=d.komut||{}, kam=d.kamera||{}, sv=d.sunucu||{};
  rozet("r_link", a.canli===true, "LINK "+(a.link_lq>=0?a.link_lq+"%":"—"));
  rozet("r_gps",  a.koken===true, "GPS "+(a.uydu||0));
  rozet("r_kip",  k.kip=="OTONOM"?null:true, k.kip||"—");
  rozet("r_insan", k.insan?true:false, "girdi: "+(k.insan||"YOK"));
  rozet("r_arm",  !!k.arm, k.arm?"ARM":"DISARM");
  // ⛔ İNİŞ KİLİDİ — panelde SESSİZ kalamaz: operatör niye komut
  //   gitmediğini görmeden anlayamaz.
  // ---- VİDEO KAYDI ----
  const vd = d.video||{};
  const bV=document.getElementById("b_video");
  bV.classList.toggle("kayitta", vd.aktif===true);
  bV.textContent = vd.aktif
    ? ("⏺ KAYITTA — "+(vd.sure_s??0)+" s · "+(vd.kare??0)+" kare · "+
       (vd.mb??0)+" MB  (durdurmak için bas)")
    : (vd.kare ? ("⏺ VİDEO KAYDI BAŞLAT   (son: "+(vd.yol||"")+")")
               : "⏺ VİDEO KAYDI BAŞLAT");
  // ---- GÖREVİ BAŞLAT ----
  window._sonDurum = d;
  const bGv=document.getElementById("b_gorev");
  const otonomda = (k.kaynak=="OTONOM");
  bGv.classList.toggle("aktif", otonomda);
  bGv.disabled = !k.arm && !otonomda;
  // ⚠ `g` ve `ko` AŞAĞIDA `const` ile tanımlanıyor — burada kullanmak
  //   "Cannot access before initialization" atıyordu (yaşandı, panel
  //   komple çöktü). Doğrudan `d`den okuyoruz.
  const _g0 = d.gudum||{}, _ko0 = d.konum||{};
  bGv.textContent = otonomda
    ? ("🚀 GÖREV SÜRÜYOR — " + (_g0.durum||"?") +
       (_g0.durum=="KALKIS" ? ("  tırmanıyor " + (_ko0.yukari??0) + " m") : ""))
    : (k.arm ? "🚀 GÖREVİ BAŞLAT (OTONOM KALKIŞ)"
             : "🚀 GÖREVİ BAŞLAT — önce ARM et");
  const di = d.inis||{};
  const inisK = (k.inis_kilidi===true);
  const bInis=document.getElementById("b_inis");
  bInis.classList.toggle("aktif", di.aktif===true);
  bInis.textContent = di.aktif
    ? ("⬇ İNİYOR — "+(di.asama||"")+"   gaz "+(di.gaz_cubugu??0).toFixed(2)+
       "   ("+(di.gecen_s??0)+" s)  · durdurmak için bas")
    : "⛔ FAILSAFE — DİKEY İNİŞ";
  const bKes=document.getElementById("b_kes");
  bKes.classList.toggle("aktif", inisK);
  bKes.textContent = inisK
    ? "⛔ PAKET KESİLDİ — kart AUTO-LAND yapıyor (kaldırmak için bas)"
    : "son çare: RC paketini kes (kartın kendi AUTO-LAND'i)";
  const rInis=document.getElementById("r_inis");
  rInis.hidden = !(inisK || di.aktif===true);
  rInis.className = "rozet kotu";
  rInis.textContent = inisK ? "⛔ PAKET KESİLDİ" : "⬇ DİKEY İNİŞ";
  // ⛔ PİLOT ÇUBUKLA DEVRALDI — operatör bunu GÖRMELİ, yoksa panelde
  //   OTONOM yazarken aracın niye güdümle uçmadığını anlayamaz.
  if(k.pilot_devraldi===true)
    document.getElementById("b_otonom").classList.add("uyari");
  rozet("r_sunucu", sv.baglandi===true, "SUNUCU "+(sv.gonderilen||0));
  // ⛔ GÜVENLİ PENCERE (Skydagger rehberi §8): ilk saniyelerde YALNIZ SAFE
  //    basılır. Operatör bunu GÖRMELİ, yoksa "komut gitmiyor" sanır.
  // ⛔ KAMERA YOKKEN /video'YA BAĞLANMA: MJPEG kalıcı bir bağlantı tutar ve
  //   tarayıcının kaynak başına ~6 bağlantısından birini SÜREKLİ meşgul eder.
  //   Kare gelmeyecekse o slotu harcamanın anlamı yok.
  kameraVar = (kam.acik===true);
  const bg=d.bag||{};
  if(bg.guvenli_pencere) rozet("r_safe",null,"SAFE PENCERESİ "+bg.guvenli_kalan+" s");
  else rozet("r_safe", bg.acik===true, bg.acik===true
       ? ("BAĞ "+(bg.tasima||"").toUpperCase()+"  RC "+(bg.yazilan||0))
       : "BAĞ YOK");
  document.getElementById("r_saat").textContent=
    sv.saat?`${sv.saat.saat}:${String(sv.saat.dakika).padStart(2,"0")}:${String(sv.saat.saniye).padStart(2,"0")}`:"";
  // ⭐ KUMANDA TAKILI OLMAK YETMEZ, OYNATILMASI GEREKİR (kullanıcı kararı).
  //   Padler yalnız kumanda GERÇEKTEN sürerken kilitlenir; pilot çubuğu
  //   bıraktıktan 3 s sonra panel kendiliğinden geri alır.
  kumandaVar = (k.insan=="kumanda") && !kmdYokSay;
  document.getElementById("padL").classList.toggle("kilitli",kumandaVar);
  document.getElementById("padR").classList.toggle("kilitli",kumandaVar);
  if(kumandaVar && k.komut){ // fiziksel kumanda -> topuzlar ONU gösterir
    yerL(k.komut[3],k.komut[0]); yerR(k.komut[2],k.komut[1]); }
  const ko=d.konum||{}, du=d.durus||{}, hz=d.hiz||{}, hd=d.hedef||{}, g=d.gudum||{};
  const hh=d.hedef_ham_konum, rt=d.rtl;
  // ---- PİL — uçuşun en kritik göstergesi ----
  const pv=a.pil_v, py=a.pil_yuzde;
  const pilTaze=(a.yas_pil!=null&&a.yas_pil<3);
  if(pv!=null&&pilTaze){
    // 6S varsayımı yok: yüzde varsa onu, yoksa hücre gerilimine göre kaba oran
    const yuz=(py!=null?py:Math.max(0,Math.min(100,(pv/6-3.3)/(4.2-3.3)*100)));
    const renk=(yuz<20?"#ff7b7b":yuz<40?"#ffd166":"#5fe08a");
    document.getElementById("pil_dolu").style.width=yuz.toFixed(0)+"%";
    document.getElementById("pil_dolu").style.background=renk;
    document.getElementById("pil_esik").style.left="20%";
    document.getElementById("pil_ozet").innerHTML=
      '<b style="color:'+renk+'">'+pv.toFixed(2)+' V</b>'+
      (py!=null?("  ·  "+py+"%"):"");
  }else{
    document.getElementById("pil_dolu").style.width="0";
    document.getElementById("pil_ozet").innerHTML=
      '<b style="color:#ff7b7b">VERİ YOK</b>';
  }
  document.getElementById("pil_tablo").innerHTML=
    sat("gerilim",(pv!=null?pv.toFixed(2)+" V":"—"))+
    sat("doluluk",(py!=null?py+" %":"—"))+
    sat("akım",(a.pil_akim!=null?a.pil_akim.toFixed(1)+" A":"—"))+
    sat("tüketilen",(a.pil_mah!=null?a.pil_mah+" mAh":"—"));

  document.getElementById("telem_ucus").innerHTML=
    sat("kaynak",(k.kaynak||"—")+(k.sebep&&k.sebep!="-"?" ("+k.sebep+")":""))+
    // ⭐ GİDEN ÇUBUKLAR — araca GERÇEKTEN ne gönderiliyor. Tezgâhta
    //   "güdüm komut üretiyor mu" sorusunun tek doğrudan cevabı budur.
    sat("RTL",(rt&&rt.aktif
        ?('<b class=orta>'+rt.asama+'</b>  eve '+(rt.mesafe??"—")+" m"+
          "  (hedef irtifa "+rt.irtifa_hedef+" m)")
        :("kapalı"+(rt&&rt.sebep?(' <span class=kotu2>'+rt.sebep+"</span>"):""))))+
    sat("çubuk T/P/R/Y",(k.komut
        ?k.komut.map(v=>(v>=0?"+":"")+v.toFixed(2)).join("  ")
        :"—"))+
    sat("dikey iniş",(di.aktif
        ?('<b class=orta>'+di.asama+'</b>  gaz çubuğu '+
          (di.gaz_cubugu??0).toFixed(2)+" / hedef "+(di.hedef_cubuk??0)+
          "   kanal "+(di.kanallar||[]).join(",")+
          "  <span class=sonuk>ALT HOLD + POS HOLD</span>")
        :"kapalı"))+
    sat("güdüm",(g.durum||"—")+" / "+(g.faz||"—"))+
    sat("kuzey / doğu",(ko.kuzey??"—")+" / "+(ko.dogu??"—")+" m")+
    sat("yükseklik",(ko.yukari??"—")+" m")+
    sat("hız",(hz.yatay??"—")+" m/s   ↕ "+(hz.dikey??"—"))+
    sat("yatış / dikilme",(du.roll??"—")+"° / "+(du.pitch??"—")+"°")+
    sat("yönelme",(du.yaw??"—")+"°")+
    sat("telemetri yaşı","gps "+(a.yas_gps??"—")+"  duruş "+(a.yas_durus??"—"))+
    // ⭐ BURUN vs ROTA — yaw'ın gerçekten BURUN olup olmadığını gösterir.
    //   Araç DÜZ İLERİ giderken (yer hızı > 2 m/s) fark ~0 olmalı.
    //   Büyük ve kalıcı fark: pusula bozuk YA DA attitude.yaw aslında
    //   rota taşıyor. İkisi de dünya->gövde dönüşümünü bozar.
    //   ⚠ Yan uçarken (kayarak) fark MEŞRU olarak büyür — bu yüzden
    //     uyarı yalnız düz gidişte anlamlıdır, karar operatörde.
    sat("burun / rota", (du.yaw??"—")+"°  /  "+(du.rota??"—")+"°"+
        (du.burun_rota_fark!=null
          ? ("   fark "+(du.burun_rota_fark>0?"+":"")+du.burun_rota_fark+"°"+
             ((du.yer_hizi>2 && Math.abs(du.burun_rota_fark)>25)
               ? " ⚠ DÜZ GİDERKEN AYRIŞIYOR" : ""))
          : ""));

  // ---- HEDEF ----
  // ⭐ MENZİL METRE OLARAK. Kutu boyutundan çıkıyor ve bugüne kadar
  //   panelde HİÇ yazmıyordu; 3 m menzil kapısı yüzünden kutu
  //   reddedilirken sebebi anlamak saatler aldı (29 Ağu 2026).
  // ⭐ MENZİL: önce kabul edilen kutu, yoksa MODELİN HAM kutusu.
  //   Hedef kaç metrede olursa olsun ekranda bir sayı görünsün — kabul
  //   edilmediyse sebebi zaten yanında yazıyor.
  const hamK=d.ham_kutu, kabulK=d.kutu;
  const kt=kabulK||hamK, kl=d.kilit||{}, op=d.optik||{};
  const kabulEdildi=!!kabulK;
  const MC=op.menzil_c||0, MIN=op.menzil_min??3, MAX=op.menzil_max??50;
  let menzil=null, kutuPx=null;
  if(kt&&MC>0){
    // güdümle AYNI ölçü: kosegen -> hypot, max -> max
    kutuPx=(op.olcu==="kosegen")?Math.hypot(kt[2],kt[3]):Math.max(kt[2],kt[3]);
    menzil=MC/kutuPx;
  }
  document.getElementById("telem_hedef").innerHTML=
    sat("GPS akışı",hd.var
        ?("<b class=iyi>VAR</b>, yaş "+hd.yas+" s")
        :(hd.n_paket
          ?("<b class=kotu2>BAYAT</b> — paket "+hd.n_paket+
            ", ulaşma "+hd.yas_ulasma+" s, <b>veri "+hd.yas_veri+" s</b>")
          :"<b class=kotu2>PAKET YOK</b>"))+
    sat("hedef GPS",(hd.ham_enlem!=null
        ?(hd.ham_enlem.toFixed(7)+" , "+hd.ham_boylam.toFixed(7))
        :"—"))+
    sat("kuzey / doğu",(hh
        ?(hh.kuzey+" / "+hh.dogu+" m   ⟶ "+hh.uzaklik+" m")
        :"— (köken kurulmadı)"))+
    sat("irtifa / hız",(hd.ham_irtifa??"—")+" m / "+(hd.ham_hiz??"—")+" m/s")+
    sat("görsel kutu",(kutuPx
        ?(Math.round(kt[2])+"x"+Math.round(kt[3])+" px"+
          (kt.length>4?('  <span class=sonuk>güven '+kt[4].toFixed(2)+"</span>"):"")+
          (kabulEdildi?'  <span class=iyi>kabul</span>'
            :'  <span class=kotu2>RED: '+(d.ham_sebep||"?")+"</span>"))
        :"—"))+
    sat("<b>görsel menzil</b>",(menzil!=null
        ?('<b class="'+(menzil<MIN?"kotu2":menzil>MAX?"orta":"iyi")+'">'+
          menzil.toFixed(1)+" m</b>"+
          (menzil<MIN?("  ⛔ "+MIN+" m altı reddedilir")
           :menzil>MAX?("  ⚠ "+MAX+" m üstü"):""))
        :"—"))+
    sat("kilit",(kl.kilit_s!=null
        ?(kl.kilit_s+" s"+(kl.sebep?("  <span class=sonuk>"+kl.sebep+"</span>"):""))
        :"—"));

  // ---- ÖN UÇUŞ KONTROL LİSTESİ ----
  const kls=d.kontrol||{maddeler:[],hazir:false,kalan:[]};
  const oz=document.getElementById("kl_ozet");
  const gecen=kls.maddeler.filter(m=>m.ok).length;
  oz.className="rozet "+(kls.hazir?"ok":"kotu");
  oz.textContent=gecen+"/"+kls.maddeler.length;
  document.getElementById("kl_liste").innerHTML=kls.maddeler.map(m=>
    '<div class=klsat title="'+(m.aciklama||"")+'">'+
    '<span class="im '+(m.ok?"iyi":"kotu2")+'">'+(m.ok?"✔":"✗")+'</span>'+
    '<span class=bas>'+m.baslik+'</span>'+
    '<span class=no>'+(m.not||"")+'</span></div>').join("");
  // ⛔ OTONOM DÜĞMESİ KİLİDİ — hakemi DEĞİŞTİRMEZ, yalnız yanlışlıkla
  //   basmayı engeller. Zorlamak isteyen onay kutusundan geçer.
  const bOto=document.getElementById("b_otonom");
  if(bOto){
    // ⛔ `bOto.disabled` KASTEN KULLANILMIYOR — bkz. onclick'teki gerekçe.
    //   Ölü düğme sahada bize bir yarışma hakkına mal oldu. Kilit yerine
    //   GÖRÜNÜR uyarı: etiket ⚠ alır, ipucu eksikleri yazar, tıklayınca
    //   onay kutusu maddeleri tek tek sayar.
    const eksik=(kls.kalan||[]);
    bOto.disabled=false;
    bOto.textContent=eksik.length?"OTONOM ⚠":"OTONOM";
    bOto.title=eksik.length
      ?("ÖN UÇUŞ EKSİK ("+eksik.length+"): "+eksik.join(", ")+
        " — basınca onay ister, otonom yine de açılabilir")
      :"otonom güdüme geç"+(kls.gorsel_ucus?"":"  (GPS güdüm, görsel kapalı)");
  }
  // ---- UÇUŞ KAYDI ----
  const ky=d.kayit;
  document.getElementById("kl_kayit").innerHTML=ky
    ?((ky.aciks?'<span class=iyi>● KAYIT</span> ':'<span class=kotu2>● DURDU</span> ')+
      ky.satir+" satır · "+ky.mb+" MB"+
      (ky.dusen?(' <span class=kotu2>· '+ky.dusen+" düşen</span>"):"")+
      (ky.hata?(' <span class=kotu2>· '+ky.hata+"</span>"):""))
    :"kayıt kapalı";

  // ---- SİSTEM ----
  document.getElementById("telem_sistem").innerHTML=
    sat("kamera",kam.acik?((kam.cihaz||"?")+"  "+(kam.genislik||0)+"x"+
        (kam.yukseklik||0)+" @"+(kam.sayac||0)):"kapalı")+
    sat("ELRS link","↑ LQ "+(a.link_lq??"—")+"  RSSI "+(a.link_rssi??"—")+" dBm"+
        (a.link_snr!=null?("  SNR "+a.link_snr):""))+
    sat("ELRS ↓ / RF",(a.link_asagi_lq??"—")+"  /  "+(a.link_rf_kipi??"—"))+
    sat("CRC hatası",a.crc_hata??"—")+
    sat("çerçeve",a.cerceve??"—")+
    sat("panel↔sunucu",(wsAcik?"WS ":"HTTP ")+postHz+" Hz"+
        (postHata?("  ⛔ "+postHata+" hata"):"")+"   fpv "+kareHz+" Hz")+
    sat("kumanda",k.kmd_takili?(k.kmd_hakim?"SÜRÜYOR":"takılı, duruyor")
        :("aranıyor… "+((k.sayac&&k.sayac.kmd_arama)||0)+" deneme  "+
          "(EdgeTX USB Mode = Joystick?)"))+
    (k.sayac?sat("hakem","otonom "+(k.sayac.otonom||0)+
        " · veto "+(k.sayac.veto||0)+" · kopuk "+(k.sayac.kmd_kopuk||0)):"")+
    (d.dikey?sat("dikey döngü",(d.dikey.aktif?"aktif":"pasif")+
        "  (pasif çağrı "+(d.dikey.pasif||0)+")"):"");
  let u=[];
  if((d.video||{}).hata)
    u.push("⚠ video kaydı hatası: "+d.video.hata);
  if((d.gudum||{}).durum=="KALKIS")
    u.unshift("🚀 OTONOM KALKIŞ — araç tırmanıyor ("+((d.konum||{}).yukari??0)+" m / "+
              "hedef 40 m). Çubuğa dokunmak görevi KESER.");
  if(k.pilot_devraldi===true && k.kip!="OTONOM")
    u.push("ℹ PİLOT ÇUBUKLA DEVRALDI — güdüm durduruldu. Otonoma dönmek "+
           "için panelde OTONOM'a bas.");
  if(di.aktif===true) u.push("⬇ DİKEY İNİŞ SÜRÜYOR ("+di.asama+
      ") — görev kesildi, araç alçalıyor. Yere değince DISARM et; "+
      "kendiliğinden disarm ETMEZ.");
  if(k.inis_kilidi===true) u.push("⛔⛔ İNİŞ KİLİDİ ETKİN — RC PAKETİ GÖNDERİLMİYOR. "+
      "Araç alıcı failsafe'inde: Betaflight AUTO-LAND. Çubuklar GİTMİYOR.");
  if(a.canli===false) u.push("⛔ TELEMETRİ AKMIYOR");
  if(a.koken===false) u.push("⚠ yerel köken kurulmadı (GPS fix bekleniyor)");
  if(k.sebep=="teslim_suresi") u.push("⛔ KUMANDA KOPUK — paket kesildi, AUTO-LAND");
  if(k.sebep=="gudum_bayat") u.push("⚠ güdüm bayat — çubuklara düşüldü");
  if(kam.acik===false) u.push("⚠ kamera yok — "+(kam.hata? kam.hata.slice(0,80)
        : "yakalama kartı takılı mı? (ls /dev/video*)"));
  // ⛔ PANEL BEKÇİSİ — donma SESSİZ olmasın
  const sessiz=(Date.now()-sonBasarili)/1000;
  if(sessiz>1.0) u.unshift("⛔ PANEL SUNUCUYA ULAŞAMIYOR ("+sessiz.toFixed(1)+
                           " s, "+postHata+" hata) — çubuklar GİTMİYOR");
  if(k.insan=="kumanda")
    u.unshift("ℹ KUMANDA SÜRÜYOR — pilot çubuğa dokundu; 3 s durursa panel geri alır");
  // --- 3B izleri besle ---
  if(ko.kuzey!==undefined) c3ekle(C3.droneIz,[ko.kuzey,ko.dogu,ko.yukari]);
  const hk=d.hedef_konum;
  if(hk) c3ekle(C3.hedefIz,[hk.kuzey,hk.dogu,hk.yukari]);
  if(jsHata) u.unshift("⛔ "+jsHata);
  document.getElementById("uyarilar").textContent=u.join("   ");
  }catch(e){ jsHata="JS(durum): "+(e&&e.message||e);
             document.getElementById("uyarilar").textContent="⛔ "+jsHata; }
}
</script></body></html>"""


# ======================================================================
#  SUNUCU
# ======================================================================
class _Islem(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _yaz(self, kod, tur, govde):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(govde)
        except Exception:
            pass

    def do_GET(self):
        if self.path == "/":
            return self._yaz(200, "text/html; charset=utf-8",
                             SAYFA.encode("utf-8"))
        if self.path == "/api/durum":
            return self._yaz(200, "application/json",
                             json.dumps(_durum()).encode("utf-8"))
        if self.path.startswith("/kare.jpg"):
            return self._tek_kare()
        if self.path == "/ws":
            return self._websocket()
        if self.path == "/video":
            return self._video()          # ⚠ eski MJPEG; artık kullanılmıyor
        self._yaz(404, "text/plain", b"yok")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            g = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            g = {}
        ks = _D["komut"]
        if self.path == "/api/manuel" and ks is not None:
            ks.panel_yaz(float(g.get("thr", 0.0)), float(g.get("pitch", 0.0)),
                         float(g.get("roll", 0.0)), float(g.get("yaw", 0.0)),
                         arm=bool(g.get("arm", False)),
                         otonom_izin=bool(g.get("izin", False)))
            return self._yaz(200, "application/json", b'{"ok":1}')
        if self.path == "/api/kip" and ks is not None:
            yeni_kip = str(g.get("kip", "MANUEL")).upper()
            try:
                ks.kip_sec(yeni_kip)
            except ValueError:
                return self._yaz(400, "application/json", b'{"ok":0}')
            # ⛔ MANUEL'E GEÇMEK RTL'İ DE KESER. Yoksa RTL sessizce
            #   ayakta kalır ve pilot tekrar OTONOM'a bastığında araç
            #   hedefe değil EVE uçar — beklenmedik davranış.
            if yeni_kip != "OTONOM" and _D.get("rtl") is not None:
                _D["rtl"].dur()
            return self._yaz(200, "application/json", b'{"ok":1}')
        if self.path == "/api/video":
            _vk = _D.get("video")
            if _vk is None:
                return self._yaz(200, "application/json",
                                 b'{"ok":0,"sebep":"video kaydi kurulu degil"}')
            if not g.get("ac"):
                _vk.dur()
                return self._yaz(200, "application/json", b'{"ok":1}')
            ok, mesaj = _vk.basla()
            return self._yaz(200, "application/json", json.dumps(
                {"ok": bool(ok), "sebep": mesaj}).encode())
        if self.path == "/api/dikey_inis":
            _in = _D.get("inis")
            if _in is None or ks is None:
                return self._yaz(200, "application/json",
                                 b'{"ok":0,"sebep":"inis kurulu degil"}')
            if not g.get("ac"):
                _in.dur()
                ks.aux_yaz({})
                return self._yaz(200, "application/json", b'{"ok":1}')
            r = _D.get("rtl")
            if r is not None:
                try:
                    r.dur()          # tek kaynak: eve dönüş varsa durur
                except Exception:
                    pass
            ok = _in.basla()
            # ⛔ Hakemin dört şartı AYNEN geçerli; kipi biz seçiyoruz ki
            #   operatör iki düğmeye basmak zorunda kalmasın.
            if ok:
                try:
                    ks.kip_sec("OTONOM")
                except ValueError:
                    pass
            return self._yaz(200, "application/json", json.dumps(
                {"ok": bool(ok), "sebep": _in.sebep}).encode())
        if self.path == "/api/inis":
            # ⛔ FAILSAFE İNİŞ — paketleri kes. RTL de kapatılır: nothing
            #   gönderilmediği için zararsızdır ama panelde "RTL sürüyor"
            #   yazması operatörü yanıltır.
            if ks is None:
                return self._yaz(200, "application/json",
                                 b'{"ok":0,"sebep":"komut sureci yok"}')
            ac = bool(g.get("ac"))
            ks.inis_kes(ac)
            if ac:
                r = _D.get("rtl")
                if r is not None:
                    try:
                        r.dur()
                    except Exception:
                        pass
            return self._yaz(200, "application/json", json.dumps(
                {"ok": 1, "kilitli": ks.inis_kilitli}).encode())
        if self.path == "/api/rtl":
            r = _D.get("rtl")
            if r is None:
                return self._yaz(200, "application/json",
                                 b'{"ok":0,"sebep":"RTL kurulu degil"}')
            if not g.get("ac"):
                r.dur()
                return self._yaz(200, "application/json", b'{"ok":1}')
            gb = _D.get("baglanti")
            hazir = bool(gb is not None and gb.cerceve.hazir)
            ok = r.basla(hazir)
            # ⛔ RTL yalnız OTONOM kipinde çalışır — hakemin dört şartı
            #   aynen geçerli. Kipi BİZ değiştiriyoruz ki pilot iki
            #   düğmeye basmak zorunda kalmasın; ama izin/kumanda
            #   şartları hâlâ hakemde.
            if ok and ks is not None:
                try:
                    ks.kip_sec("OTONOM")
                except ValueError:
                    pass
            return self._yaz(200, "application/json", json.dumps(
                {"ok": bool(ok), "sebep": r.sebep}).encode())
        if self.path == "/api/koken" and _D["baglanti"] is not None:
            ok, mesaj = _D["baglanti"].kokeni_kur(bool(g.get("zorla")))
            return self._yaz(200, "application/json",
                             json.dumps({"ok": ok, "mesaj": mesaj}).encode())
        self._yaz(404, "application/json", b'{"ok":0}')

    # ---------------- WEBSOCKET ----------------
    def _websocket(self):
        anahtar = self.headers.get("Sec-WebSocket-Key")
        if not anahtar:
            return self._yaz(400, "text/plain", b"websocket degil")
        kabul = base64.b64encode(hashlib.sha1(
            (anahtar + _WS_SIHIR).encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", kabul)
        self.end_headers()
        sok = self.connection
        with _ws_kilit:
            _ws_istemciler.add(sok)
        try:
            while True:
                c = _ws_oku(self.rfile)
                if c is None:
                    break
                opkod, yuk = c
                if opkod == 0x8:                    # kapat
                    break
                if opkod == 0x9:                    # ping -> pong
                    sok.sendall(_ws_cerceve(yuk, 0xA))
                    continue
                if opkod != 0x1:
                    continue
                try:
                    m = json.loads(yuk.decode("utf-8"))
                except Exception:
                    continue
                self._ws_komut(m)
        except Exception:
            pass
        finally:
            with _ws_kilit:
                _ws_istemciler.discard(sok)

    @staticmethod
    def _ws_komut(m):
        """Panelden gelen tek mesaj. ⛔ HTTP yoluyla AYNI işi yapar."""
        ks = _D["komut"]
        c = m.get("c")
        if c == "cubuk" and ks is not None:
            ks.panel_yaz(float(m.get("thr", 0.0)), float(m.get("pitch", 0.0)),
                         float(m.get("roll", 0.0)), float(m.get("yaw", 0.0)),
                         arm=bool(m.get("arm", False)),
                         otonom_izin=bool(m.get("izin", False)))
        elif c == "kip" and ks is not None:
            try:
                ks.kip_sec(str(m.get("kip", "MANUEL")).upper())
            except ValueError:
                pass
        elif c == "koken" and _D["baglanti"] is not None:
            _D["baglanti"].kokeni_kur(bool(m.get("zorla")))

    # ---------------- TEK KARE (varsayılan yol) ----------------
    def _tek_kare(self):
        """Tek bir JPEG döndürür ve BAĞLANTIYI BIRAKIR.

        ⛔⛔ MJPEG NİYE BIRAKILDI — SAHADA DEFALARCA DONDU (2026-08-29):
           `<img src="/video">` KALICI bir HTTP bağlantısı tutar. Chrome'un
           kaynak başına eşzamanlı bağlantı sınırı HTTP/1.1'de 6'dır. Biri
           kalıcı olarak MJPEG'e gidince geriye 5 kalır; üstüne 30 Hz POST
           ve 5 Hz durum isteği binince havuz tıkanır ve SAYFA DONAR —
           sunucu tarafı tamamen sağlıklı olsa bile (ölçüldü: 0.8 ms, 0 hata).
           Tek kare yolu bağlantıyı hemen bırakır; havuz asla dolmaz.
        """
        import cv2
        kam = _D["kamera"]
        if kam is None:
            return self._yaz(503, "text/plain", b"kamera yok")
        kare, _t, _s = kam.son_kare()
        if kare is None:
            return self._yaz(503, "text/plain", b"kare yok")
        ok, buf = cv2.imencode(".jpg", _cizim(kare.copy()),
                               [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return self._yaz(500, "text/plain", b"kodlanamadi")
        self._yaz(200, "image/jpeg", buf.tobytes())

    # ---------------- MJPEG (ESKİ YOL — kullanılmıyor) ----------------
    def _video(self):
        import cv2
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=k")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        son = -1
        try:
            while True:
                kam = _D["kamera"]
                if kam is None:
                    time.sleep(0.2)
                    continue
                kare, _t, sayac = kam.son_kare()
                if kare is None or sayac == son:
                    time.sleep(0.02)
                    continue
                son = sayac
                kare = _cizim(kare.copy())
                ok, buf = cv2.imencode(".jpg", kare,
                                       [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    continue
                b = buf.tobytes()
                self.wfile.write(b"--k\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: " + str(len(b)).encode() +
                                 b"\r\n\r\n" + b + b"\r\n")
        except Exception:
            return


def _cizim(kare):
    """AV kilit dörtgeni + kutu. ⛔ ÖLÇÜT `dow/gudum/kilit.py`den gelir."""
    import cv2
    from dow.ayarlar import Ayar
    h, w = kare.shape[:2]
    x0 = int(w * Ayar.KILIT_KIRP_X); x1 = int(w * (1 - Ayar.KILIT_KIRP_X))
    y0 = int(h * Ayar.KILIT_KIRP_Y); y1 = int(h * (1 - Ayar.KILIT_KIRP_Y))
    cv2.rectangle(kare, (x0, y0), (x1, y1), (90, 200, 255), 1)
    cv2.putText(kare, "AV", (x0 + 4, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (90, 200, 255), 1)
    def _kesikli_dikdortgen(im, a, b, renk, kal, adim=10):
        """Kesikli dikdörtgen — KABUL EDİLENden ayırt edilebilsin diye.
        OpenCV'de kesikli çizgi yok; parça parça çiziyoruz."""
        for x in range(a[0], b[0], adim * 2):
            cv2.line(im, (x, a[1]), (min(x + adim, b[0]), a[1]), renk, kal)
            cv2.line(im, (x, b[1]), (min(x + adim, b[0]), b[1]), renk, kal)
        for y in range(a[1], b[1], adim * 2):
            cv2.line(im, (a[0], y), (a[0], min(y + adim, b[1])), renk, kal)
            cv2.line(im, (b[0], y), (b[0], min(y + adim, b[1])), renk, kal)

    kutu = _D.get("son_kutu")
    if kutu:
        cx, cy, bw, bh = kutu[:4]
        p0 = (int(cx - bw / 2), int(cy - bh / 2))
        p1 = (int(cx + bw / 2), int(cy + bh / 2))
        kilitli = bool(_D.get("olcut", {}).get("bu_kare"))
        cv2.rectangle(kare, p0, p1, (90, 255, 120) if kilitli else (0, 165, 255), 2)
    # ⛔ REDDEDİLEN TESPİT — model gördü, güdüm kabul etmedi.
    #   Bunu çizmezsek ekranda hiçbir iz kalmaz ve "model çalışmıyor"
    #   sanılır. 29 Ağu 2026'da tam bu oldu: sebep menzil kapısıydı
    #   (1.5 m < MENZIL_MIN_M 3 m), model kusursuz çalışıyordu.
    ham = _D.get("ham_kutu")
    if ham and not kutu:
        cx, cy, bw, bh = ham[:4]
        q0 = (int(cx - bw / 2), int(cy - bh / 2))
        q1 = (int(cx + bw / 2), int(cy + bh / 2))
        _kesikli_dikdortgen(kare, q0, q1, (80, 80, 255), 2)
        sb = _D.get("ham_sebep") or "red"
        gv = (" %.2f" % ham[4]) if len(ham) > 4 else ""
        cv2.putText(kare, "RED: %s%s" % (sb, gv), (q0[0], max(14, q0[1] - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 255), 2)
    o = _D.get("olcut") or {}
    if o:
        cv2.putText(kare, "KILIT %.1f/%.1f s" % (o.get("kilit_s", 0.0),
                                                 Ayar.KILIT_GEREKLI_S),
                    (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (90, 255, 120) if o.get("saglandi") else (200, 200, 200), 2)
    return kare


_sunucu = None


def baslat(port=None):
    global _sunucu
    port = port or int(os.environ.get("DOW_PANEL_PORT", 8810))
    _sunucu = ThreadingHTTPServer(("0.0.0.0", port), _Islem)
    _sunucu.daemon_threads = True
    threading.Thread(target=_sunucu.serve_forever, daemon=True,
                     name="panel").start()
    threading.Thread(target=_ws_yayinla, daemon=True, name="panel-ws").start()
    return port


def durdur():
    if _sunucu:
        _sunucu.shutdown()
