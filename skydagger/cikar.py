#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SKYDAGGER BACKEND'İNİ .exe İÇİNDEN ÇIKARIR
================================================================================
⛔ NİYE GEREKLİ: komite backend'i `skydagger-backend.exe` olarak veriyor ama
   bu bir **PyInstaller ile paketlenmiş Python 3.12 uygulamasıdır** — Windows'a
   özgü hiçbir yanı yok. Kodun içinde açıkça şu yazıyor:

     "Cross-platform 'is this a USB serial adapter?' check. Linux exposes it
      in the device name (/dev/ttyUSB0, /dev/ttyACM0)"

   Yani Linux'ta DOĞAL çalışır. Wine'a gerek YOKTUR.

⚠ WINE NİYE OLMADI (denendi, 2026-08-29):
     Ubuntu'nun wine 6.0.3'ü  -> propsys.dll.VariantToString yok, çöküyor
     GE-Proton11-5'in wine'ı  -> GLIBC 2.38 istiyor, sistemde 2.35 var
   Üçüncü yol (bu dosya) ikisinden de sağlam: bağımlılık YOK, konteyner YOK.

⛔ KOMİTENİN KODU DEĞİŞTİRİLMEZ. Bu araç yalnızca ÇIKARIR; bytecode'a
   dokunmaz. Çalıştırma `yukleyici.py` ile yapılır.

Kullanım:
    python3 cikar.py "<yol>/skydagger-backend.exe" [hedef_dizin]
================================================================================
"""
import os
import struct
import sys
import zlib

SIHIR = b"MEI\014\013\012\013\016"


def cikar(exe_yolu, hedef):
    d = open(exe_yolu, "rb").read()
    i = d.rfind(SIHIR)
    if i < 0:
        raise SystemExit("⛔ PyInstaller arşiv imzası yok — bu dosya beklenen "
                         "biçimde değil (komite sürümü değişmiş olabilir).")
    # CArchive kuyruğu: sihir(8) uzunluk(4) toc_ofs(4) toc_uz(4) pyver(4) lib(64)
    kuyruk = d[i:i + 88]
    _, paket_uz, toc_ofs, toc_uz, pyver = struct.unpack("!8sIIII", kuyruk[:24])
    pylib = kuyruk[24:88].rstrip(b"\x00").decode()
    bas = i + 88 - paket_uz
    toc = d[bas + toc_ofs: bas + toc_ofs + toc_uz]

    girdiler, p = [], 0
    while p < len(toc):
        (uz,) = struct.unpack("!i", toc[p:p + 4])
        ofs, veri_uz, ham_uz, sikis, tip = struct.unpack("!IIIBc", toc[p + 4:p + 18])
        ad = toc[p + 18:p + uz].rstrip(b"\x00").decode("utf-8", "replace")
        girdiler.append((ad, ofs, veri_uz, sikis, tip.decode()))
        p += uz

    os.makedirs(hedef, exist_ok=True)
    bulundu = None
    for ad, ofs, vu, sk, tp in girdiler:
        if tp != "s" or ad != "backend":
            continue
        ham = d[bas + ofs: bas + ofs + vu]
        if sk:
            ham = zlib.decompress(ham)
        bulundu = os.path.join(hedef, "backend.pyc")
        open(bulundu, "wb").write(ham)
    if bulundu is None:
        raise SystemExit("⛔ arşivde 'backend' betiği yok. Girdiler: %s"
                         % [g[0] for g in girdiler if g[4] == "s"])
    print("✔ çıkarıldı : %s  (%d bayt)" % (bulundu, os.path.getsize(bulundu)))
    print("  Python    : %d.%d  (%s)" % (pyver // 100, pyver % 100, pylib))
    print("  ⛔ Bu bytecode Python %d.%d İSTER; 3.10 onu okuyamaz "
          "('bad marshal data')." % (pyver // 100, pyver % 100))
    return bulundu, pyver


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    cikar(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".")
