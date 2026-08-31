#!/usr/bin/env bash
# ==============================================================================
# SKYDAGGER BACKEND KURULUMU — bir kez çalıştırılır
# ==============================================================================
# Komitenin `skydagger-backend.exe` dosyasını Linux'ta DOĞAL çalışır hale getirir.
# Wine gerekmez. Yaptıkları:
#   1) Taşınabilir Python 3.12 indirir (~/.skydagger/py312) — sudo GEREKMEZ
#   2) pyserial kurar
#   3) .exe içinden backend'i çıkarır (~/.skydagger/backend.pyc)
#
# Kullanım:  ./kur.sh [skydagger-backend.exe yolu]
set -eu
cd "$(dirname "$0")"
KOK="$HOME/.skydagger"
PY_SURUM="3.12.11"
PY_TAG="20250818"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/cpython-${PY_SURUM}+${PY_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"

kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }
yesil(){   printf '\033[32m%s\033[0m\n' "$*"; }

EXE="${1:-}"
if [ -z "$EXE" ]; then
    for a in \
        "$HOME/İndirilenler"/*/skydagger-yarismaci-paketi/skydagger-backend.exe \
        "$HOME/İndirilenler"/skydagger-yarismaci-paketi/skydagger-backend.exe \
        "$HOME/Downloads"/*/skydagger-yarismaci-paketi/skydagger-backend.exe ; do
        [ -f "$a" ] && EXE="$a" && break
    done
fi
if [ ! -f "${EXE:-}" ]; then
    kirmizi "  HATA: skydagger-backend.exe bulunamadı."
    echo   "        Kullanım:  ./kur.sh /tam/yol/skydagger-backend.exe"
    exit 1
fi
echo "  backend  : $EXE"
mkdir -p "$KOK"

# --- 1) taşınabilir Python 3.12 ---
if [ -x "$KOK/py312/bin/python3" ]; then
    yesil "  Python 3.12: zaten kurulu"
else
    echo "  Python 3.12 indiriliyor (~100 MB, sudo gerekmez)..."
    curl -fL --progress-bar -o "$KOK/py312.tar.gz" "$PY_URL"
    mkdir -p "$KOK/py312"
    tar -xzf "$KOK/py312.tar.gz" -C "$KOK/py312" --strip-components=1
    rm -f "$KOK/py312.tar.gz"
    yesil "  Python 3.12: kuruldu"
fi
"$KOK/py312/bin/python3" -V

# --- 2) pyserial ---
"$KOK/py312/bin/python3" -m pip install -q --disable-pip-version-check pyserial
"$KOK/py312/bin/python3" -c "import serial; print('  pyserial :', serial.__version__)"

# --- 3) backend'i çıkar ---
python3 cikar.py "$EXE" "$KOK"

echo
yesil "  ✔ KURULUM TAMAM"
echo "     Başlatmak için:  ./reel/skydagger/baslat_backend.sh"
