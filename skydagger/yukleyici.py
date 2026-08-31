#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SKYDAGGER BACKEND YÜKLEYİCİSİ — çıkarılmış bytecode'u Linux'ta çalıştırır
================================================================================
`cikar.py` ile alınan `backend.pyc` bir PyInstaller arşiv girdisidir: standart
16 baytlık .pyc başlığı YOKTUR, doğrudan marshal'lanmış bir kod nesnesidir.
Bu yüzden `import` edilemez; `marshal.loads` + `exec` ile çalıştırılır.

⛔ TTY ŞART. Backend `readline` kullanıyor (Tab tamamlama, yukarı-ok geçmişi).
   Boruya bağlanınca konsol hiç açılmıyor ve HİÇ ÇIKTI VERMİYOR — hata da
   vermiyor. Çözüm sarmalayıcı betikte: `script -qfec ... /dev/null`.
   (Bu deponun CLAUDE.md §9'unda yazılı MAVProxy tuzağının aynısı.)

⛔ KOMİTENİN KODUNA DOKUNULMAZ. Burada yapılan tek şey onu çalıştırmaktır.
================================================================================
"""
import marshal
import os
import sys

BURASI = os.path.dirname(os.path.abspath(__file__))
PYC = os.environ.get("SKY_PYC") or os.path.join(BURASI, "backend.pyc")

if not os.path.exists(PYC):
    raise SystemExit(
        "⛔ backend.pyc yok: %s\n"
        "   Önce kurulumu çalıştır:  ./reel/skydagger/kur.sh" % PYC)

try:
    kod = marshal.loads(open(PYC, "rb").read())
except ValueError as e:
    raise SystemExit(
        "⛔ bytecode okunamadı (%s).\n"
        "   Neredeyse kesin sebep: YANLIŞ PYTHON SÜRÜMÜ. Backend Python 3.12\n"
        "   ister; bu yorumlayıcı %d.%d.\n"
        "   Doğru çalıştırma:  ./reel/skydagger/baslat_backend.sh"
        % (e, sys.version_info[0], sys.version_info[1]))

sys.argv = ["backend.py"] + sys.argv[1:]
exec(kod, {"__name__": "__main__",
           "__file__": os.path.join(BURASI, "backend.py"),
           "__package__": None,
           "__builtins__": __builtins__})
