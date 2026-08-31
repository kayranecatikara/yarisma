#!/usr/bin/env bash
# ==============================================================================
# SKYDAGGER BACKEND'İ BAŞLATIR  (Linux, Wine YOK)
# ==============================================================================
# ⛔ TTY SARMALAYICISI ŞART: backend `readline` kullanıyor. Boruya bağlanınca
#    konsol hiç açılmıyor ve HİÇ ÇIKTI VERMİYOR — hata da vermiyor.
#    `script -qfec` bu yüzden var (CLAUDE.md §9'daki MAVProxy tuzağı).
set -u
cd "$(dirname "$0")"
KOK="$HOME/.skydagger"
kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }
sari(){    printf '\033[33m%s\033[0m\n' "$*"; }
yesil(){   printf '\033[32m%s\033[0m\n' "$*"; }

[ -x "$KOK/py312/bin/python3" ] || { kirmizi "  HATA: kurulum yapılmamış -> ./kur.sh"; exit 1; }
[ -f "$KOK/backend.pyc" ]       || { kirmizi "  HATA: backend.pyc yok -> ./kur.sh"; exit 1; }

# ==============================================================================
# ÖNCEKİ BACKEND'İ TEMİZLE  (başlatmadan önce, her seferinde)
# ==============================================================================
# ⛔ NİYE BURADA: backend `yukleyici.py` ile çalışıyor, dolayısıyla süreç adı
#   "backend.py" DEĞİL. Kullanıcının `pkill -f backend.py` yazması işe
#   yaramıyordu ve port 8765 tutulu kalıyordu ("Address already in use").
#   Bu, operatörün bilmesi gereken bir ayrıntı olmamalı — betik halleder.
#
# ⛔ DESENLER KÖŞELİ PARANTEZLE KIRILIR: `pkill -f` kendi kabuğunu da
#   eşleyebilir ve öldürebilir (CLAUDE.md §9'da yazılı, bu depoda yaşandı,
#   exit 144). `[y]ukleyici` deseni kendi komut satırıyla eşleşmez.
temizle() {
    local bulundu=0
    for desen in "[y]ukleyici\.py" "[b]ackend\.pyc"; do
        if pgrep -f "$desen" >/dev/null 2>&1; then
            bulundu=1
            pkill -f "$desen" 2>/dev/null || true
        fi
    done
    # `script` sarmalayıcısı da kalabilir
    pkill -f "[s]cript -qfec .*yukleyici" 2>/dev/null || true
    [ "$bulundu" = "1" ] && sari "  önceki backend kapatıldı"

    # Portlar gerçekten boşalana kadar bekle (en fazla 5 s)
    for i in $(seq 1 25); do
        if ! (exec 3<>/dev/tcp/127.0.0.1/8765) 2>/dev/null; then
            exec 3<&- 2>/dev/null || true
            return 0
        fi
        exec 3<&- 2>/dev/null || true
        [ "$i" = "10" ] && { pkill -9 -f "[y]ukleyici\.py" 2>/dev/null || true; }
        sleep 0.2
    done
    kirmizi "  ⛔ 8765 hâlâ tutulu. Kim tutuyor:"
    (command -v ss >/dev/null && ss -ltnp 2>/dev/null | grep 8765) \
        || (command -v lsof >/dev/null && lsof -i :8765 2>/dev/null) \
        || echo "     (ss/lsof yok)"
    return 1
}

if [ "${1:-}" = "--kapat" ]; then
    temizle && yesil "  backend kapatıldı."
    exit 0
fi
temizle || exit 1

if [ -e /dev/ttyUSB0 ] && [ ! -w /dev/ttyUSB0 ]; then
    kirmizi "  UYARI: /dev/ttyUSB0 yazılabilir değil"
    echo   "         sudo usermod -aG dialout \$USER   (sonra OTURUMU KAPAT-AÇ)"
fi
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet ModemManager 2>/dev/null; then
    kirmizi "  UYARI: ModemManager çalışıyor — ESP32'nin portuna AT komutu"
    kirmizi "         gönderip akışı bozabilir:"
    echo   "         sudo systemctl disable --now ModemManager"
fi

cat <<'BILGI'

  ┌─ SKYDAGGER BACKEND ─────────────────────────────────────────────┐
  │  Web/HTTP  http://127.0.0.1:8765                                │
  │  Komut TCP 127.0.0.1:8766   (satır protokolü + telemetri)       │
  │  RC   UDP  127.0.0.1:8767   (bizim yazılım buraya basar)        │
  ├─ SIRA (rehber §5) ──────────────────────────────────────────────┤
  │  /connect     → ESP32 portu bulunur                             │
  │  RC_ENABLE    → SONRA modüle 2S pili tak → ışık MAVİ olmalı     │
  │  STOP         → sarı (durdurmanın çalıştığı doğrulanır)         │
  │  EXTERNAL     → bizim yazılım devralır                          │
  ├─ KAPANIŞ (⛔ sırayla) ──────────────────────────────────────────┤
  │  EXTERNAL STOP  →  /disconnect  →  pil çek  →  USB çek          │
  │  ⛔ /disconnect ATLANIRSA ESP kötü boot moduna düşebilir         │
  └─────────────────────────────────────────────────────────────────┘

BILGI
export SKY_PYC="$KOK/backend.pyc"
exec script -qfec "$KOK/py312/bin/python3 -u $(pwd)/yukleyici.py $*" /dev/null
