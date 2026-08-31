# -*- coding: utf-8 -*-
"""
================================================================================
KAMERA AYARI — gerçek kameranın optiğini SAHADA ölç
================================================================================
NİYE GEREKLİ
  `dow/gorus/kamera.py` içindeki sabitler SİMÜLASYONDA ölçüldü (F_PX=540.4,
  TILT=26.50°, MENZIL_C=997, 1920x1080). Gerçek uçakta kamera BAŞKA: başka
  mercek, başka montaj açısı, başka yakalama çözünürlüğü. Bu sabitler
  değiştirilmezse görsel güdüm menzili ve kerterizi YANLIŞ hesaplar — ve
  hata SESSİZDİR, hiçbir yerde patlamaz.

NE ÖLÇÜYORUZ — üçü de gözle, dedektöre İHTİYAÇ YOK
  ┌────────────┬──────────────────────────────────────────────────────────┐
  │ F_PX       │ odak uzaklığı, piksel cinsinden. Kameranın "yakınlığı".  │
  │ TILT_DEG   │ kamera ekseninin uçağın burnuna göre YUKARI açısı.       │
  │ MENZIL_C   │ menzil sabiti: R = MENZIL_C / kutu_genisligi             │
  └────────────┴──────────────────────────────────────────────────────────┘

TÜRETME (§0.2 — hiçbir şey varsayılmıyor)

  1) F_PX — delikli iğne (pinhole) kamera modelinden.
     Genişliği S metre olan bir cisim, R metre uzakta, görüntüde w piksel
     genişliğinde görünür. Benzer üçgenler:

         w / F_PX = S / R        =>       F_PX = w · R / S

     Yani: hedefi ÖLÇÜLMÜŞ bir mesafeye koy, görüntüde kanat uçlarını
     tıkla (= w piksel), kanat açıklığını (= S metre) bil. F_PX çıkar.
     Talon kanat açıklığı S = 1.718 m (belge).

     ⚠ HANGİ VARSAYIM: mercek bozulması (distorsiyon) yok sayılıyor ve
       fx = fy (kare piksel) kabul ediliyor. Geniş açı FPV merceklerinde
       kadrajın KENARINDA bu bozulur — bu yüzden ölçümü hedefi kadrajın
       ORTASINA koyarak yap.

  2) MENZIL_C — geometrik hâli doğrudan yukarıdakidir:

         MENZIL_C = F_PX · S = w · R

     ⚠ AMA dedektörün kutusu gerçek kanat açıklığından biraz GENİŞTİR
       (kutu gövdeyi ve payı da içine alır). Simülasyonda ölçüldü:
       geometrik 540.4 · 1.718 = 928.4 iken dedektör kutusuyla FİT edilen
       değer 997.0 — yani %7.4 pay. Dedektör gerçek görüntüde çalışmaya
       başlayınca MENZIL_C bu araçla DEĞİL, gerçek kutulardan yeniden
       fit edilmelidir. O güne kadar geometrik değer + %7.4 makul bir
       başlangıçtır ve bu araç onu da yazar.

  3) TILT_DEG — ufuk çizgisinden.
     Uçağı YERDE, gövdesi YATAY olacak şekilde koy. Kamera burnun TILT
     derece yukarısına baktığı için gerçek ufuk, görüntünün ORTASININ
     ALTINDA kalır. Ufuk çizgisini tıkla (y_ufuk piksel):

         TILT = atan( (CY − y_ufuk) / F_PX )        CY = görüntü_yüksekliği/2

     ⚠ HANGİ VARSAYIM: gövdenin yatay olduğu. Uçak yerde burnu yukarı
       duruyorsa o açı TILT'e karışır. Düz bir zemine, kanatlar yatay
       koy; şüphedeysen telefon su terazisiyle gövdeyi kontrol et.

KULLANIM
    python3 gercek/kamera_ayari.py            # tarayıcı: localhost:8020
    python3 gercek/kamera_ayari.py --port 8020 --kamera oto

  Sonuçlar `logs/kamera_ayari.json` altına yazılır ve panel, doğrudan
  `baslat_drone.sh`'a yapıştırılacak `export` satırlarını üretir.

⛔ BU ARAÇ GÜDÜMÜ ÇALIŞTIRMAZ. Yalnız kamera görüntüsü okur ve ölçüm
  toplar. Uçağa hiçbir komut göndermez.
================================================================================
"""
import argparse
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BURASI = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(BURASI)
for _p in (KOK, os.path.dirname(KOK)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gercek.kamera_yakala import (Kamera, KameraCfg,        # noqa: E402
                                  cihazlari_tara)

KAYIT = os.path.join(KOK, "logs", "kamera_ayari.json")

_D = {"kam": None, "olcumler": [], "ufuk_y": None, "w": 0, "h": 0,
      "fov": None, "fov_eksen": "yatay", "tilt_elle": None}
_kilit = threading.Lock()


# ---------------------------------------------------------------- hesap
def f_px_spectan(fov_deg, w, h, eksen="yatay"):
    """Üretici FOV'undan F_PX. Delikli iğne modeli:

           tan(FOV/2) = (yarı_boyut_px) / F_PX
        => F_PX = yarı_boyut_px / tan(FOV/2)

    `eksen` HANGİ boyutun FOV'u verildiğini söyler. Bu ÖNEMLİ: üreticiler
    genelde KÖŞEGEN FOV yazar ama bunu belirtmez. 720x480'de köşegen kabul
    etmek yatay kabule göre F_PX'i %20 büyütür.

    ⚠ SPEC ÖLÇÜM DEĞİLDİR. Üretici FOV'ları yuvarlanmış ve çoğu zaman
      abartılıdır; ayrıca yakalama kartı görüntüyü kırpıyor/ölçekliyorsa
      gerçek FOV yazandan farklı olur. Bu değer BAŞLANGIÇ içindir; kanat
      ucu ölçümü onu doğrular ya da düzeltir.
    """
    if not fov_deg or fov_deg <= 0 or fov_deg >= 180 or not w or not h:
        return None
    yari = {"yatay": w / 2.0, "dikey": h / 2.0,
            "kosegen": math.hypot(w, h) / 2.0}.get(eksen)
    if yari is None:
        return None
    return yari / math.tan(math.radians(fov_deg / 2.0))



def f_px_hesapla(olcumler, kanat_m):
    """Her ölçümden F_PX çıkar, medyanını al.

    MEDYAN, ortalama DEĞİL: tek bir kötü tıklama (kanat ucunu ıskalamak)
    ortalamayı çeker ama medyanı çekmez.
    """
    tekil = []
    for o in olcumler:
        # ⭐ HER ÖLÇÜM KENDİ CİSİM GENİŞLİĞİNİ TAŞIR (2026-08-29).
        #   Kalibrasyon için Talon ŞART DEĞİL: genişliği bilinen HERHANGİ
        #   bir cisim olur (cetvel, kapı kanadı). Formül S'yi bilmek ister,
        #   cismin ne olduğunu değil — bu, kapalı ortamda kalibrasyonu
        #   mümkün kılar. `genislik` yoksa eski davranış (Talon kanadı).
        s_m = float(o.get("genislik") or kanat_m)
        if o["px"] > 0 and o["mesafe"] > 0 and s_m > 0:
            tekil.append(o["px"] * o["mesafe"] / s_m)
    if not tekil:
        return None, [], None
    s = sorted(tekil)
    n = len(s)
    med = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    # dağılım: en büyük sapma yüzdesi — ölçümün ne kadar tutarlı olduğu
    sapma = max(abs(v - med) / med for v in s) * 100.0
    return med, tekil, sapma


def tilt_hesapla(ufuk_y, yukseklik, f_px):
    if ufuk_y is None or not f_px:
        return None
    cy = yukseklik / 2.0
    return math.degrees(math.atan((cy - ufuk_y) / f_px))


def rapor():
    with _kilit:
        olc = list(_D["olcumler"])
        uy = _D["ufuk_y"]
        w, h = _D["w"], _D["h"]
        fov, fov_eksen = _D["fov"], _D["fov_eksen"]
    # ⭐ HER ÖLÇÜM KENDİ CİSİM GENİŞLİĞİNİ TAŞIR.
    #   Kalibrasyon için Talon ŞART DEĞİL: genişliği bilinen HERHANGİ bir
    #   cisim olur (cetvel, kapı kanadı, masa). Formül S'yi bilmek ister,
    #   cismin ne olduğunu değil. Bu, kalibrasyonu kapalı ortamda da
    #   mümkün kılar — Talon'u 30 m uzağa koyacak yer aramaya gerek yok.
    kanat = float(os.environ.get("DOW_OPTIK_KANAT", "1.718"))
    f, tekil, sapma = f_px_hesapla(olc, kanat)
    f_spec = f_px_spectan(fov, w, h, fov_eksen)
    # ⛔ ÖLÇÜM SPEC'İ EZER. Spec yalnız ölçüm yokken kullanılır.
    f_kul = f if f else f_spec
    with _kilit:
        tilt_elle = _D["tilt_elle"]
    # ⛔ ÖLÇÜM ELLE GİRİLENİ EZER — ufka tıkladıysan o geçerlidir.
    tilt = tilt_hesapla(uy, h, f_kul) if h else None
    if tilt is None:
        tilt = tilt_elle
    c_geo = f_kul * kanat if f_kul else None
    # Simülasyonda ölçülen dedektör payı: 997.0 / (540.4·1.718) = 1.0738
    PAY = 997.0 / (540.4 * 1.718)
    c_det = c_geo * PAY if c_geo else None
    return {
        "cozunurluk": [w, h], "kanat_m": kanat,
        "n_olcum": len(olc), "olcumler": olc,
        "f_px": round(f, 1) if f else None,
        "f_px_spec": round(f_spec, 1) if f_spec else None,
        "f_px_kullanilan": round(f_kul, 1) if f_kul else None,
        "kaynak": "ölçüm" if f else ("spec" if f_spec else None),
        "fov": fov, "fov_eksen": fov_eksen,
        "spec_olcum_farki": (round(abs(f - f_spec) / f_spec * 100.0, 1)
                             if (f and f_spec) else None),
        "f_px_tekil": [round(v, 1) for v in tekil],
        "sapma_yuzde": round(sapma, 1) if sapma is not None else None,
        "ufuk_y": uy,
        "tilt_deg": round(tilt, 2) if tilt is not None else None,
        "tilt_kaynak": ("ufuk ölçümü" if (uy is not None and f_kul)
                        else ("elle" if tilt_elle is not None else None)),
        "menzil_c_geometrik": round(c_geo, 1) if c_geo else None,
        "menzil_c_onerilen": round(c_det, 1) if c_det else None,
        "dedektor_payi": round(PAY, 4),
    }


def export_satirlari(r):
    if not r["f_px_kullanilan"]:
        return "# önce FOV gir ya da en az bir ölçüm al"
    s = ["# --- kamera optiği — kamera_ayari.py, kaynak: %s (%s) ---"
         % (r["kaynak"].upper(), time.strftime("%Y-%m-%d %H:%M")),
         "export DOW_OPTIK_W=%d" % r["cozunurluk"][0],
         "export DOW_OPTIK_H=%d" % r["cozunurluk"][1],
         "export DOW_OPTIK_F_PX=%.1f" % r["f_px_kullanilan"]]
    if r["kaynak"] == "spec":
        s.insert(1, "# ⚠ F_PX ÜRETİCİ FOV'undan (%.0f° %s) — ÖLÇÜM DEĞİL."
                 % (r["fov"], r["fov_eksen"]))
        s.insert(2, "#   Kanat ucu ölçümüyle DOĞRULA: üretici FOV'ları")
        s.insert(3, "#   yuvarlanmış/abartılı olur ve yakalama kartı")
        s.insert(4, "#   görüntüyü kırpıyorsa gerçek FOV bundan farklıdır.")
    if r["tilt_deg"] is not None:
        s.append("export DOW_OPTIK_TILT=%.2f   # %s"
                 % (r["tilt_deg"], r["tilt_kaynak"]))
    else:
        s.append("# DOW_OPTIK_TILT — ufuk ölçümü YAPILMADI, sim değeri kalır")
    s.append("export DOW_OPTIK_MENZIL_C=%.1f" % r["menzil_c_onerilen"])
    s.append("#   (geometrik %.1f + dedektör payı %.1f%%; dedektör gerçek "
             "görüntüde\n#    çalışınca gerçek kutulardan YENİDEN fit et)"
             % (r["menzil_c_geometrik"], (r["dedektor_payi"] - 1) * 100))
    return "\n".join(s)


def kaydet():
    try:
        os.makedirs(os.path.dirname(KAYIT), exist_ok=True)
        r = rapor()
        r["export"] = export_satirlari(r)
        gecici = KAYIT + ".yeni"
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        os.replace(gecici, KAYIT)
    except OSError:
        pass


def yukle():
    try:
        with open(KAYIT, encoding="utf-8") as f:
            d = json.load(f)
        with _kilit:
            _D["olcumler"] = d.get("olcumler", [])
            _D["ufuk_y"] = d.get("ufuk_y")
            _D["fov"] = d.get("fov")
            _D["fov_eksen"] = d.get("fov_eksen", "yatay")
            _D["tilt_elle"] = d.get("tilt_elle")
        return len(_D["olcumler"])
    except (OSError, ValueError):
        return 0


# ---------------------------------------------------------------- sayfa
SAYFA = r"""<!doctype html><html lang=tr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>KAMERA AYARI</title><style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#0b0e13;color:#dfe6f0;
  font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;min-height:100vh}
.ust{display:flex;gap:10px;align-items:center;padding:8px 12px;
     background:#131924;border-bottom:1px solid #223;flex-wrap:wrap}
.ust b{font-size:15px;letter-spacing:1px}
.rozet{padding:3px 9px;border-radius:4px;font-weight:700;font-size:12px}
.ok{background:#123d1e;color:#5fe08a}.kotu{background:#3d1212;color:#ff7b7b}
.uyari{background:#3d3312;color:#ffd166}
main{display:grid;grid-template-columns:1fr 340px;gap:10px;padding:10px}
@media(max-width:980px){main{grid-template-columns:1fr}}
.kutu{background:#131924;border:1px solid #223;border-radius:8px;padding:10px}
.kutu h3{font-size:11px;letter-spacing:1.5px;color:#7d8aa0;margin-bottom:7px;
         text-transform:uppercase}
.tuval{position:relative;line-height:0}
#kare{width:100%;display:block;border-radius:6px;background:#080b10;
      cursor:crosshair}
#ciz{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
button{padding:9px 6px;border:1px solid #2a3550;border-radius:6px;
  background:#1b2333;color:#dfe6f0;font:700 12px ui-monospace,monospace;
  cursor:pointer;flex:1}
button:hover{background:#243049}
button.ana{background:#1d4ed8;border-color:#60a5fa;color:#fff}
button.sec{background:#14532d;border-color:#22c55e;color:#c9f7d5}
button.tehlike{background:#7f1d1d;border-color:#ef4444}
.satir{display:flex;gap:6px;margin-top:8px}
label{display:block;color:#7d8aa0;font-size:11px;margin-top:8px}
input{width:100%;padding:7px;background:#0b0e13;color:#dfe6f0;
  border:1px solid #2a3550;border-radius:4px;font:13px ui-monospace,monospace}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
td,th{padding:3px 4px;text-align:left;border-bottom:1px solid #1c2438}
th{color:#7d8aa0;font-weight:400}
.mesaj{margin-top:9px;font-size:11.5px;min-height:32px;color:#ffd166;
  line-height:1.5}
.sonuc{font-size:12px;line-height:1.7}
.sonuc b{color:#5fe08a;font-size:14px}
pre{background:#080b10;border:1px solid #2a3550;border-radius:5px;padding:9px;
  font-size:11px;overflow-x:auto;margin-top:8px;color:#9ccaff;line-height:1.6;
  white-space:pre-wrap}
.yardim{color:#7d8aa0;font-size:11px;line-height:1.6;margin-top:6px}
</style></head><body>
<div class=ust><b>KAMERA AYARI</b>
  <span id=r_kam class="rozet kotu">KAMERA</span>
  <span id=r_kip class="rozet uyari">ODAK</span>
  <span id=r_n class="rozet uyari">0 ölçüm</span>
  <span style="flex:1"></span><span id=r_coz style="color:#7d8aa0"></span>
</div>
<main>
  <div class=kutu>
    <h3 id=baslik>1) Kanat ucuna tıkla · 2) Öbür kanat ucuna tıkla</h3>
    <div class=tuval>
      <img id=kare alt="kamera görüntüsü">
      <svg id=ciz viewBox="0 0 1000 1000" preserveAspectRatio=none></svg>
    </div>
    <div class=yardim id=yardim></div>
  </div>
  <div>
    <div class=kutu>
      <h3>Ölçüm kipi</h3>
      <div class=satir>
        <button id=k_odak class=sec>ODAK</button>
        <button id=k_ufuk>TILT</button>
        <button id=k_spec>SPEC</button>
      </div>
      <div id=spec_alan style="display:none">
        <label>Üretici FOV (derece)</label>
        <input id=fov type=number value=120 step=1 min=1 max=179>
        <label>Bu FOV hangi eksen için?</label>
        <select id=fov_eksen>
          <option value=yatay>YATAY (genişlik boyunca)</option>
          <option value=kosegen selected>KÖŞEGEN (üreticiler genelde bunu yazar)</option>
          <option value=dikey>DİKEY (yükseklik boyunca)</option>
        </select>
        <div class=yardim>⚠ Spec ÖLÇÜM DEĞİLDİR — üretici FOV'ları
          yuvarlanmış/abartılı olur ve yakalama kartı görüntüyü kırpıyorsa
          gerçek FOV bundan farklıdır. Başlangıç değeri verir; kanat ucu
          ölçümü onu doğrular. <b>Ölçüm varsa spec'i EZER.</b></div>
        <label>TILT (derece) — biliniyorsa elle gir</label>
        <input id=tilt_elle type=number value="" step=0.5 placeholder="ör. 25">
        <div class=yardim>Kameranın burna göre YUKARI açısı. Montaj açısını
          biliyorsan buraya yaz; ufuk ölçümü yaparsan <b>o ezer</b>.</div>
        <div class=satir><button id=b_spec class=ana>UYGULA</button></div>
      </div>
      <div id=odak_alan>
        <label>Cisme ÖLÇÜLEN mesafe (m)</label>
        <input id=mesafe type=number value=5 step=0.1 min=0.3>
        <div class=yardim>Şerit metre ile ölç. Tahmin etme — bu sayı
          doğrudan F_PX'e çarpan olarak giriyor.</div>
        <label>Cismin GERÇEK genişliği (m)</label>
        <input id=genislik type=number value=1.718 step=0.001 min=0.01>
        <div class=yardim>Talon kanat açıklığı <b>1.718</b>. Ama Talon ŞART
          DEĞİL: genişliği bilinen herhangi bir cisim olur — cetvel, kapı
          kanadı, masa kenarı. Formül cismin NE olduğunu değil, KAÇ METRE
          olduğunu bilmek ister. Kapalı ortamda böyle kalibre edebilirsin.</div>
        <div class=satir><button id=b_dondur class=ana>KAREYİ DONDUR</button></div>
      </div>
      <div class=mesaj id=mesaj></div>
    </div>

    <div class=kutu style="margin-top:10px">
      <h3>Ölçümler</h3>
      <table id=liste><tr><th>#</th><th>mesafe</th><th>cisim</th><th>px</th>
        <th>F_PX</th></tr></table>
      <div class=satir>
        <button id=b_geri>SON ÖLÇÜMÜ SİL</button>
        <button id=b_temizle class=tehlike>TÜMÜNÜ SİL</button>
      </div>
    </div>

    <div class=kutu style="margin-top:10px">
      <h3>Sonuç</h3>
      <div class=sonuc id=sonuc>—</div>
      <pre id=export># önce en az bir ölçüm al</pre>
    </div>
  </div>
</main>
<script>
let kip="odak", nokta=[], dondu=false, son=null, IW=0, IH=0;
const im=document.getElementById("kare"), svg=document.getElementById("ciz");
const mes=(t,k)=>{const e=document.getElementById("mesaj");
  e.textContent=t;e.style.color=k?"#ff7b7b":"#5fe08a";};

// --- canlı görüntü: tek kare, sırayla. Kalıcı bağlantı YOK — Chrome'un
//     origin başına 6 bağlantı sınırı paneli dondurmuştu, aynı hatayı
//     burada tekrarlamıyoruz.
function kareAl(){
  if(dondu)return;
  const y=new Image();
  y.onload=()=>{im.src=y.src;IW=y.naturalWidth;IH=y.naturalHeight;
    setTimeout(kareAl,120);};
  y.onerror=()=>setTimeout(kareAl,600);
  y.src="/kare.jpg?t="+Date.now();
}
kareAl();

function ciz(){
  const W=1000,H=1000;
  let s="";
  if(kip==="odak"){
    // ⛔ MERCEK BOZULMASI KILAVUZU. Geniş açı FPV merceğinde düz çizgiler
    //   kadrajın KENARINDA kavis yapar; F_PX orada yanlış çıkar. Ölçümü
    //   bu dikdörtgenin İÇİNDE yap — orta %50'lik bölge.
    s+=`<rect x="${W*0.25}" y="${H*0.25}" width="${W*0.5}" height="${H*0.5}"`+
       ` fill="none" stroke="#ffd166" stroke-width="2" stroke-dasharray="10 8"/>`;
    s+=`<text x="${W*0.25+8}" y="${H*0.25-8}" fill="#ffd166"`+
       ` font-family="monospace" font-size="22">ÖLÇÜMÜ BU ALANDA YAP</text>`;
    nokta.forEach(p=>{const x=p[0]/IW*W,y=p[1]/IH*H;
      s+=`<line x1="${x}" y1="${y-28}" x2="${x}" y2="${y+28}" stroke="#5fe08a" stroke-width="2"/>`;
      s+=`<line x1="${x-28}" y1="${y}" x2="${x+28}" y2="${y}" stroke="#5fe08a" stroke-width="2"/>`;});
    if(nokta.length===2){
      const a=nokta[0],b=nokta[1];
      s+=`<line x1="${a[0]/IW*W}" y1="${a[1]/IH*H}" x2="${b[0]/IW*W}" y2="${b[1]/IH*H}" stroke="#6fb2ff" stroke-width="3"/>`;
    }
  }else if(son&&son.ufuk_y!=null&&IH){
    const y=son.ufuk_y/IH*H;
    s+=`<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="#ffd166" stroke-width="3"/>`;
    s+=`<line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="#3d5a80" stroke-width="2" stroke-dasharray="8 8"/>`;
  }
  svg.innerHTML=s;
}

im.addEventListener("click",async e=>{
  if(!IW){mes("⛔ görüntü yok",1);return;}
  const r=im.getBoundingClientRect();
  const px=(e.clientX-r.left)/r.width*IW, py=(e.clientY-r.top)/r.height*IH;
  if(kip==="ufuk"){
    const d=await post("/api/ufuk",{y:py});
    mes(d.mesaj,!d.ok); durum(); return;
  }
  if(!dondu){mes("⛔ önce KAREYİ DONDUR",1);return;}
  nokta.push([px,py]); ciz();
  if(nokta.length===1)mes("bir uç işaretlendi — şimdi ÖBÜR kanat ucuna tıkla");
  if(nokta.length===2){
    const gen=Math.abs(nokta[1][0]-nokta[0][0]);
    const m=parseFloat(document.getElementById("mesafe").value);
    const S=parseFloat(document.getElementById("genislik").value);
    const d=await post("/api/olcum",{px:gen,mesafe:m,genislik:S});
    mes(d.mesaj,!d.ok);
    nokta=[]; dondu=false; kareAl(); durum();
  }
});

async function post(u,g){return (await (await fetch(u,{method:"POST",
  body:JSON.stringify(g)})).json());}

document.getElementById("b_dondur").onclick=()=>{
  if(dondu){dondu=false;nokta=[];ciz();kareAl();
    document.getElementById("b_dondur").textContent="KAREYİ DONDUR";
    mes("canlı görüntüye dönüldü");return;}
  dondu=true;nokta=[];ciz();
  document.getElementById("b_dondur").textContent="ÇÖZ (canlıya dön)";
  mes("kare donduruldu — kanat uçlarına tıkla");
};
document.getElementById("k_odak").onclick=()=>kipSec("odak");
document.getElementById("k_ufuk").onclick=()=>kipSec("ufuk");
document.getElementById("k_spec").onclick=()=>kipSec("spec");
document.getElementById("b_spec").onclick=async()=>{
  const d=await post("/api/spec",{
    fov:parseFloat(document.getElementById("fov").value),
    eksen:document.getElementById("fov_eksen").value,
    tilt:document.getElementById("tilt_elle").value});
  mes(d.mesaj,!d.ok); durum();};
function kipSec(k){
  kip=k;nokta=[];
  ["odak","ufuk","spec"].forEach(x=>{
    document.getElementById("k_"+x).className=(k===x)?"sec":"";});
  document.getElementById("odak_alan").style.display=(k==="odak")?"":"none";
  document.getElementById("spec_alan").style.display=(k==="spec")?"":"none";
  document.getElementById("r_kip").textContent=k.toUpperCase();
  const B={odak:"1) Kanat ucuna tıkla · 2) Öbür kanat ucuna tıkla",
           ufuk:"Uçak YERDE ve GÖVDESİ YATAY iken UFUK ÇİZGİSİNE tıkla",
           spec:"Üretici FOV'undan F_PX hesapla (ölçüm yerine geçmez)"};
  const Y={odak:"Cismi SARI ÇERÇEVENİN içine koy — geniş açı merceğinde kenarda bozulma var ve F_PX yanlış çıkar. Farklı mesafelerde 3-4 ölçüm al.",
           ufuk:"Kesikli mavi çizgi görüntünün ortası. Sarı çizgi senin işaretlediğin ufuk. Aradaki fark TILT açısını verir.",
           spec:"F_PX = (yarı_boyut_px) / tan(FOV/2). Hangi eksen olduğunu doğru seç — 720x480'de köşegen kabul etmek yatay kabule göre F_PX'i %20 büyütür."};
  document.getElementById("baslik").textContent=B[k];
  document.getElementById("yardim").textContent=Y[k];
  ciz();
  if(k!=="odak")dondu=false,kareAl();
}
document.getElementById("b_geri").onclick=async()=>{
  mes((await post("/api/sil",{son:1})).mesaj);durum();};
document.getElementById("b_temizle").onclick=async()=>{
  if(!confirm("Bütün ölçümler silinsin mi?"))return;
  mes((await post("/api/sil",{hepsi:1})).mesaj);durum();};

async function durum(){
  let d;try{d=await (await fetch("/api/durum")).json();}catch(e){return;}
  son=d.rapor;
  const rk=document.getElementById("r_kam");
  rk.className="rozet "+(d.kamera?"ok":"kotu");
  rk.textContent=d.kamera?"KAMERA ✔":"KAMERA YOK";
  document.getElementById("r_coz").textContent=
    son.cozunurluk[0]?(son.cozunurluk[0]+"x"+son.cozunurluk[1]):"";
  document.getElementById("r_n").textContent=son.n_olcum+" ölçüm";
  let h="<tr><th>#</th><th>mesafe</th><th>cisim</th><th>px</th><th>F_PX</th></tr>";
  son.olcumler.forEach((o,i)=>{
    h+=`<tr><td>${i+1}</td><td>${o.mesafe} m</td>`+
       `<td>${o.genislik||son.kanat_m} m</td>`+
       `<td>${Math.round(o.px)}</td><td>${son.f_px_tekil[i]||"—"}</td></tr>`;});
  document.getElementById("liste").innerHTML=h;
  let s="";
  if(son.f_px_kullanilan){
    s+=`F_PX &nbsp; <b>${son.f_px_kullanilan}</b> px`+
       ` <span style="color:#7d8aa0">(${son.kaynak})</span>`;
    if(son.kaynak==="spec")
      s+=` <span style="color:#ffd166">⚠ ölçüm değil</span>`;
    if(son.spec_olcum_farki!=null)
      s+=`<br><span style="color:${son.spec_olcum_farki>25?"#ff7b7b":"#7d8aa0"}">`+
         `spec ${son.f_px_spec} px — ölçümle %${son.spec_olcum_farki} fark</span>`;
    if(son.sapma_yuzde!=null)
      s+=` <span style="color:${son.sapma_yuzde>10?"#ff7b7b":"#7d8aa0"}">`+
         `(ölçümler arası en büyük sapma %${son.sapma_yuzde})</span>`;
    s+="<br>";
    s+=son.tilt_deg!=null
      ? `TILT &nbsp; <b>${son.tilt_deg}</b>°`+
        ` <span style="color:#7d8aa0">(${son.tilt_kaynak})</span><br>`
      : `TILT &nbsp; <span style="color:#ffd166">yok</span><br>`;
    s+=`MENZIL_C &nbsp; <b>${son.menzil_c_onerilen}</b> px·m`+
       ` <span style="color:#7d8aa0">(geometrik ${son.menzil_c_geometrik}`+
       ` + dedektör payı)</span>`;
    if(son.n_olcum<3)
      s+=`<br><span style="color:#ffd166">⚠ ${son.n_olcum} ölçüm — `+
         `en az 3 farklı mesafede ölç</span>`;
  }else s="—";
  document.getElementById("sonuc").innerHTML=s;
  document.getElementById("export").textContent=d.export;
  ciz();
}
setInterval(durum,900); durum(); kipSec("odak");
</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _y(self, kod, tur, g):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(g)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(g)
        except Exception:
            pass

    def _c(self, ok, mesaj, **ek):
        return self._y(200, "application/json",
                       json.dumps({"ok": bool(ok), "mesaj": mesaj,
                                   **ek}).encode())

    def do_GET(self):
        yol = self.path.split("?", 1)[0]
        if yol == "/":
            return self._y(200, "text/html; charset=utf-8", SAYFA.encode())
        if yol == "/kare.jpg":
            kam = _D["kam"]
            if kam is None:
                return self._y(503, "text/plain", b"kamera yok")
            kare, _t, _s = kam.son_kare()
            if kare is None:
                return self._y(503, "text/plain", b"kare yok")
            import cv2
            with _kilit:
                _D["h"], _D["w"] = kare.shape[0], kare.shape[1]
            ok, buf = cv2.imencode(".jpg", kare,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return self._y(500, "text/plain", b"kodlanamadi")
            return self._y(200, "image/jpeg", buf.tobytes())
        if yol == "/api/durum":
            r = rapor()
            return self._y(200, "application/json", json.dumps({
                "kamera": _D["kam"] is not None,
                "rapor": r, "export": export_satirlari(r)}).encode())
        return self._y(404, "text/plain", b"yok")

    def do_POST(self):
        yol = self.path.split("?", 1)[0]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            g = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._c(False, "bozuk istek")

        if yol == "/api/olcum":
            try:
                px = float(g["px"]); mesafe = float(g["mesafe"])
            except (KeyError, TypeError, ValueError):
                return self._c(False, "px / mesafe okunamadı")
            if px < 4:
                return self._c(False, "kanat açıklığı %d px — iki tıklama "
                                      "birbirine çok yakın" % px)
            if not (1.0 <= mesafe <= 2000.0):
                return self._c(False, "mesafe %g m — 1..2000 m arası olmalı"
                               % mesafe)
            kanat = float(os.environ.get("DOW_OPTIK_KANAT", "1.718"))
            try:
                gen = float(g.get("genislik") or kanat)
            except (TypeError, ValueError):
                return self._c(False, "cisim genişliği sayı değil")
            if not (0.01 <= gen <= 50.0):
                return self._c(False, "cisim genişliği %g m — 0.01..50 m arası"
                               % gen)
            with _kilit:
                _D["olcumler"].append({"px": round(px, 1), "mesafe": mesafe,
                                       "genislik": gen, "t": time.time()})
            kaydet()
            return self._c(True, "✔ %d px @ %g m · cisim %g m  ->  F_PX %.0f"
                           % (px, mesafe, gen, px * mesafe / gen))

        if yol == "/api/ufuk":
            try:
                y = float(g["y"])
            except (KeyError, TypeError, ValueError):
                return self._c(False, "y okunamadı")
            with _kilit:
                _D["ufuk_y"] = round(y, 1)
                h = _D["h"]
            kaydet()
            r = rapor()
            if r["f_px"] is None:
                return self._c(True, "ufuk işaretlendi — ama TILT için önce "
                                     "F_PX gerekiyor (ODAK ölçümü yap)")
            return self._c(True, "✔ ufuk y=%.0f (orta %.0f)  ->  TILT %.2f°"
                           % (y, h / 2.0, r["tilt_deg"]))

        if yol == "/api/spec":
            try:
                fov = float(g["fov"])
                eksen = str(g.get("eksen", "yatay"))
            except (KeyError, TypeError, ValueError):
                return self._c(False, "FOV okunamadı")
            if not (1.0 <= fov < 180.0):
                return self._c(False, "FOV %g° — 1..179 arası olmalı" % fov)
            if eksen not in ("yatay", "dikey", "kosegen"):
                return self._c(False, "eksen: yatay | dikey | kosegen")
            te = g.get("tilt")
            with _kilit:
                _D["fov"], _D["fov_eksen"] = fov, eksen
                if te not in (None, ""):
                    try:
                        te = float(te)
                    except (TypeError, ValueError):
                        return self._c(False, "TILT sayı değil")
                    if not (-90.0 < te < 90.0):
                        return self._c(False, "TILT %g° — -90..90 arası" % te)
                    _D["tilt_elle"] = te
                w, h = _D["w"], _D["h"]
            kaydet()
            f = f_px_spectan(fov, w, h, eksen)
            if f is None:
                return self._c(False, "kamera çözünürlüğü henüz bilinmiyor")
            kanat = float(os.environ.get("DOW_OPTIK_KANAT", "1.718"))
            return self._c(True, "✔ FOV %g° (%s) @ %dx%d  ->  F_PX %.1f"
                                 "   ·   40 px'lik hedef %.1f m uzakta demek"
                           % (fov, eksen, w, h, f, f * kanat / 40.0))
        if yol == "/api/sil":
            with _kilit:
                if g.get("hepsi"):
                    _D["olcumler"] = []
                    _D["ufuk_y"] = None
                    m = "hepsi silindi"
                elif _D["olcumler"]:
                    _D["olcumler"].pop()
                    m = "son ölçüm silindi"
                else:
                    m = "silinecek ölçüm yok"
            kaydet()
            return self._c(True, m)
        return self._c(False, "bilinmeyen uç")


def main():
    ap = argparse.ArgumentParser(description="Kamera optiğini sahada ölç")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--kamera", default=os.environ.get("DOW_KAM_KAYNAK", "oto"))
    ap.add_argument("--tara", action="store_true",
                    help="video cihazlarını ve destekledikleri biçimleri "
                         "listele, sonra çık")
    ap.add_argument("--fourcc", default=None,
                    help="piksel biçimini zorla (YUYV / MJPG). "
                         "'yok' = dokunma. Analog kartlar genelde YUYV.")
    a = ap.parse_args()

    if a.tara:
        print("=" * 66)
        print("  VİDEO CİHAZLARI")
        print("=" * 66)
        liste = cihazlari_tara()
        if not liste:
            print("  ⛔ hiç /dev/videoN yok — yakalama kartı takılı mı?")
            return 1
        def _bicimler(yol):
            """Cihazın DESTEKLEDİĞİ piksel biçimleri (v4l2-ctl'den).

            ⛔ NİYE ÖNEMLİ: kod varsayılan olarak MJPG zorluyor. Ucuz analog
              yakalama kartlarının çoğu YALNIZ YUYV verir; MJPG dayatılınca
              sürücü ya reddeder ya da baytları yanlış yorumlar — ekranda
              mor/yeşil renk kayması ve yatay çizgiler görürsün.
              (29 Ağu 2026'da tam bu görüldü.)
            """
            try:
                import subprocess
                c = subprocess.run(["v4l2-ctl", "-d", yol,
                                    "--list-formats-ext"],
                                   capture_output=True, text=True, timeout=5)
                import re as _re
                return _re.findall(r"\'(\w+)\'", c.stdout)
            except Exception:
                return []

        for c in liste:
            k = c.get("cozunurluk") or (0, 0)
            b = _bicimler(c["yol"])
            print("  %-14s %-24s %s  %-9s %s"
                  % (c["yol"], (c.get("ad") or "?")[:24],
                     "KARE VAR " if c.get("kare") else "kare YOK ",
                     "%dx%d" % (k[0], k[1]),
                     ("biçim: " + "/".join(b)) if b else ""))
        # ---- HÜKÜM: yakalama kartı var mı, kare veriyor mu ----
        # ⛔ SAHADA EN ÇOK ZAMAN YİYEN ŞEY BU. Cihaz listesini basıp
        #   kullanıcıya yorumlatmak yetmiyor; iki ayrı arıza var ve
        #   çareleri farklı:
        #     (a) kart HİÇ YOK          -> USB'ye tak
        #     (b) kart VAR, kare YOK    -> karta video SİNYALİ girmiyor
        #   İkisini ayırmadan "kamera çalışmıyor" demek, saatler yiyor.
        KART_IPUCU = ("usb video", "uvc", "capture", "grabber", "stk",
                      "av to", "easycap", "macro")
        DAHILI_IPUCU = ("integrated", "webcam", "hd camera", "facetime")

        def _kart_mi(c):
            ad = (c.get("ad") or "").lower()
            if any(x in ad for x in KART_IPUCU):
                return True
            return not any(x in ad for x in DAHILI_IPUCU)

        kartlar = [c for c in liste if _kart_mi(c)]
        kareli = [c for c in kartlar if c.get("kare")]
        print("")
        print("  " + "-" * 64)
        if not kartlar:
            print("  ⛔ YAKALAMA KARTI BULUNAMADI")
            print("     Listede yalnız dahili/USB webcam var.")
            print("")
            print("     YAP: kartı USB'ye TAK, birkaç saniye bekle, tekrar")
            print("          çalıştır. Takılıysa başka bir USB portu dene.")
            print("          Kart takılıyken burada 'USB Video' benzeri bir")
            print("          satır ÇIKMALI.")
            print("  " + "-" * 64)
            return 2
        if not kareli:
            print("  ⚠ KART VAR AMA KARE VERMİYOR")
            for c in kartlar:
                print("     %s  (%s)" % (c["yol"], c.get("ad") or "?"))
            print("")
            print("     Bu, USB sorunu DEĞİL — karta VİDEO SİNYALİ girmiyor.")
            print("     YAP, sırayla:")
            print("       1. Drone'a pil bağla (VTX'in beslenmesi lazım)")
            print("       2. FPV alıcısını aç ve kanalı VTX ile eşle")
            print("       3. Alıcının video çıkışını karta bağla (sarı RCA)")
            print("       4. Alıcıda görüntü var mı — küçük ekranı varsa bak")
            print("       5. Tekrar:  python3 gercek/kamera_ayari.py --tara")
            print("  " + "-" * 64)
            return 3
        c = kareli[0]
        k = c.get("cozunurluk") or (0, 0)
        b = _bicimler(c["yol"])
        istenen = os.environ.get("DOW_KAM_FOURCC", "MJPG")
        print("  ✔ YAKALAMA KARTI HAZIR: %s  %dx%d" % (c["yol"], k[0], k[1]))
        ek = ""
        if b and istenen and istenen.upper() not in [x.upper() for x in b]:
            print("")
            print("  ⛔ PİKSEL BİÇİMİ UYUŞMUYOR — RENKLER BOZUK ÇIKAR")
            print("     kod %s istiyor, kart yalnız %s veriyor."
                  % (istenen, "/".join(b)))
            print("     Belirti: mor/yeşil renk kayması, yatay çizgiler.")
            ek = " --fourcc %s" % b[0]
            print("")
            print("     ÇÖZÜM — kalibrasyonda:")
            print("       python3 gercek/kamera_ayari.py --kamera %s%s"
                  % (c["yol"], ek))
            print("     ve uçuşta:")
            print("       DOW_KAM_FOURCC=%s DOW_KAM_KAYNAK=%s ./baslat_drone.sh"
                  % (b[0], c["yol"]))
            print("  " + "-" * 64)
            return 0
        print("")
        print("     Kalibrasyonu bununla başlat:")
        print("       python3 gercek/kamera_ayari.py --kamera %s" % c["yol"])
        print("")
        print("     Uçuşta da AYNI cihaz kullanılmalı:")
        print("       DOW_KAM_KAYNAK=%s ./baslat_drone.sh" % c["yol"])
        print("  " + "-" * 64)
        return 0

    print("=" * 66)
    print("  KAMERA AYARI — http://localhost:%d" % a.port)
    print("=" * 66)
    n = yukle()
    if n:
        print("  önceki %d ölçüm geri yüklendi (%s)" % (n, KAYIT))

    if a.fourcc is not None:
        KameraCfg.FOURCC = "" if a.fourcc.lower() in ("yok", "none", "")\
            else a.fourcc.upper()
    KameraCfg.KAYNAK = a.kamera
    kam = Kamera()
    if kam.ac():
        time.sleep(0.6)
        w, h = kam.cozunurluk()
        with _kilit:
            _D["kam"], _D["w"], _D["h"] = kam, w, h
        print("  KAMERA    : %s  %dx%d   biçim: %s"
              % (a.kamera, w, h, KameraCfg.FOURCC or "(dokunulmadı)"))
        print("")
        print("  ⚠ RENKLER MOR/YEŞİL ÇIKIYORSA piksel biçimi yanlıştır:")
        print("      python3 gercek/kamera_ayari.py --kamera %s --fourcc YUYV"
              % a.kamera)
        print("    Kartın ne desteklediğini görmek için:  --tara")
        print("")
        print("  ⚠ ÖLÇÜMÜ HANGİ ÇÖZÜNÜRLÜKTE YAPARSAN, UÇUŞTA DA O")
        print("    ÇÖZÜNÜRLÜK KULLANILMALI. F_PX çözünürlükle ölçeklenir.")
    else:
        print("  KAMERA    : ⛔ %s" % kam.hata)
        print("  (yakalama kartı takılı mı? DOW_KAM_KAYNAK ile elle ver)")
    print("")
    print("  ⛔ Bu araç uçağa HİÇBİR komut göndermez; yalnız görüntü okur.")
    print("  Ctrl+C ile çık.\n")

    s = ThreadingHTTPServer(("0.0.0.0", a.port), _H)
    s.daemon_threads = True
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if _D["kam"]:
            _D["kam"].kapat()
        kaydet()
        print("\n  kaydedildi: %s" % KAYIT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
