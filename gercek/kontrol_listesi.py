# -*- coding: utf-8 -*-
"""
================================================================================
ÖN UÇUŞ KONTROL LİSTESİ — otonoma geçmeden önce ne sağlanmalı
================================================================================
NİYE: bugüne kadar operatör altı ayrı yeri gözüyle tarayıp karar veriyordu
(pil, uydu, köken, hedef akışı, kamera, kumanda). Biri atlanınca sebebi
uçuşta anlaşılıyordu. Liste bunu TEK YERDE ve OTOMATİK yapar.

⛔⛔ HAKEME DOKUNULMADI. `komut.py`'deki DÖRT ŞART (panel OTONOM · pilot
   izni · taze setpoint · kumanda bağı) emniyet kapısıdır, kanıtlanmıştır
   ve R39 bekçisiyle korunur. Bu liste ONUN YERİNE GEÇMEZ; panelde
   OTONOM düğmesini kilitler, yani operatörün YANLIŞLIKLA otonoma
   geçmesini engeller. Arıza yönü GÜVENLİ: liste bozulursa otonom
   AÇILMAZ, elle uçmaya düşülür.

⛔ ZORLAMA YOLU AÇIK BIRAKILDI. Sahada beklenmedik bir durumda listenin
   bir maddesi yanlış kırmızı yanabilir; operatörün otonomdan mahrum
   kalması bundan daha tehlikelidir. `zorla=True` ile geçilir ve bu
   uçuş kaydına DÜŞER (hangi madde zorlandı).

MADDELER — hepsi telemetriden OTOMATİK, tahmin yok
================================================================================
"""

#: (anahtar, başlık, zorunlu mu, açıklama)
MADDELER = [
    ("bag",     "ELRS bağı canlı",        True,
     "Telemetri akmıyorsa güdüm aracın nerede olduğunu bilmez."),
    ("pil",     "Pil gerilimi okunuyor",  True,
     "Bataryayı göremeden uçmak, uçağı kaybetmenin en kolay yoludur."),
    ("gps",     "GPS fix ve ≥10 uydu",    True,
     "Az uyduyla konum metrelerce kayar; GPS fazı hedefi ıskalar."),
    ("koken",   "Yerel köken kuruldu",    True,
     "Köken kurulmadan tüm metre hesabı yapılamaz."),
    ("hedef",   "Hedef GPS'i taze",       True,
     "Bayat hedef, uçağın ARTIK OLMADIĞI yere nişan almaktır."),
    ("kamera",  "Kamera kare veriyor",    True,
     "Görsel faz kamerasız çalışmaz; İSTASYON'da takılı kalır."),
    ("gorsel",  "Görsel güdüm açık",      True,
     "--gorsel verilmediyse dedektör hiç yüklenmez."),
    ("kumanda", "Kumanda takılı",         True,
     "Otonomu kesmenin en hızlı yolu kumanda çubuğudur."),
]

#: eşikler — hepsi ölçülmüş/şartname değerleri
UYDU_MIN = 10
HEDEF_MAX_YAS_S = 1.5          # hedef.py MAX_YAS_S ile aynı olmalı
KAMERA_MAX_YAS_S = 1.0
PIL_MIN_V = 6.0                # bunun altı "okunmuyor" demek, "boş" değil


def degerlendir(d):
    """Panel durum sözlüğünden listeyi çıkar.

    Döner: {"maddeler": [{anahtar, baslik, ok, not, zorunlu}], "hazir": bool}
    """
    a = d.get("arac") or {}
    hd = d.get("hedef") or {}
    kam = d.get("kamera") or {}
    k = d.get("komut") or {}

    pil_v = a.get("pil_v")
    uydu = a.get("uydu") or 0
    kam_yas = kam.get("yas")

    sonuc = {}
    sonuc["bag"] = (bool(a.get("canli")),
                    "telemetri akmıyor" if not a.get("canli") else "")
    sonuc["pil"] = (pil_v is not None and pil_v >= PIL_MIN_V,
                    "gerilim okunamıyor" if pil_v is None
                    else ("%.2f V — telemetri şüpheli" % pil_v
                          if pil_v < PIL_MIN_V else "%.2f V" % pil_v))
    sonuc["gps"] = (uydu >= UYDU_MIN, "%d uydu (≥%d gerekir)" % (uydu, UYDU_MIN))
    sonuc["koken"] = (bool(a.get("koken")),
                      "" if a.get("koken") else "KÖKEN KUR'a bas")
    sonuc["hedef"] = (bool(hd.get("var")),
                      "" if hd.get("var")
                      else ("paket yok" if not hd.get("n_paket")
                            else "BAYAT — veri yaşı %s s" % hd.get("yas_veri")))
    sonuc["kamera"] = (bool(kam.get("acik")) and kam_yas is not None
                       and kam_yas < KAMERA_MAX_YAS_S,
                       "kamera kapalı" if not kam.get("acik")
                       else ("kare gelmiyor (yaş %s s)" % kam_yas
                             if kam_yas is None or kam_yas >= KAMERA_MAX_YAS_S
                             else ""))
    sonuc["gorsel"] = (bool(d.get("gorsel_aktif")),
                       "" if d.get("gorsel_aktif")
                       else "--gorsel ile başlat")
    sonuc["kumanda"] = (bool(k.get("kmd_takili")),
                        "" if k.get("kmd_takili") else "kumanda bulunamadı")

    maddeler = []
    hazir = True
    for anahtar, baslik, zorunlu, aciklama in MADDELER:
        ok, notu = sonuc.get(anahtar, (False, "bilinmiyor"))
        maddeler.append({"anahtar": anahtar, "baslik": baslik, "ok": bool(ok),
                         "not": notu, "zorunlu": zorunlu,
                         "aciklama": aciklama})
        if zorunlu and not ok:
            hazir = False
    return {"maddeler": maddeler, "hazir": hazir,
            "kalan": [m["anahtar"] for m in maddeler
                      if m["zorunlu"] and not m["ok"]]}
