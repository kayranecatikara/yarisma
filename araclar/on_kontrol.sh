#!/usr/bin/env bash
# ==============================================================================
# ÖN KONTROL — uçuştan önce her şey yerinde mi, TEK KOMUT
# ==============================================================================
# ⛔ NİYE: yarışma günü "acaba taktım mı" diye tahmin edilmez. Bu betik
#   donanımı, ağı ve yazılımı tek tek yoklar ve EKSİK OLANI SÖYLER.
#   Hiçbir şey başlatmaz, sunucuya HİÇBİR ŞEY GÖNDERMEZ (yalnız okur).
#
# Kullanım:  ~/projects/yarisma/araclar/on_kontrol.sh
set -u
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1

SUNUCU_IP="${AG_SUNUCU:-10.0.0.10}"
SUNUCU_PORT="${AG_PORT:-10001}"
ARAYUZ="${AG_ARAYUZ:-enp4s0}"
EKSIK=0

ye(){ printf '  \033[32m✔\033[0m %s\n' "$*"; }
ky(){ printf '  \033[31m✗\033[0m %s\n' "$*"; EKSIK=$((EKSIK+1)); }
sa(){ printf '  \033[33m⚠\033[0m %s\n' "$*"; }
bas(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

echo "=============================================================="
echo "  ÖN KONTROL"
echo "=============================================================="

bas "DONANIM"
if ls /dev/ttyUSB* >/dev/null 2>&1; then
    ye "ESP32 (ELRS)      $(ls /dev/ttyUSB* | tr '\n' ' ')"
else
    ky "ESP32 TAKILI DEĞİL — /dev/ttyUSB* yok"
fi

KAM=""
for d in /dev/video*; do
    [ -e "$d" ] || continue
    if v4l2-ctl -d "$d" --list-formats >/dev/null 2>&1; then KAM="$KAM $d"; fi
done
if [ -n "$KAM" ]; then
    ye "kamera cihazları $KAM"
    sa "hangisi FPV kartı:  python3 gercek/kamera_ayari.py --tara"
else
    ky "KAMERA YOK — /dev/video* bulunamadı"
fi

if ls /dev/input/js* >/dev/null 2>&1; then
    ye "kumanda           $(ls /dev/input/js* | tr '\n' ' ')"
else
    ky "KUMANDA TAKILI DEĞİL — ön uçuş listesi 8/8 olmaz"
    sa "EdgeTX: SYS → Hardware → USB Mode = Joystick"
fi

bas "AĞ ve SUNUCU"
IPV=$(ip -4 addr show "$ARAYUZ" 2>/dev/null | grep -oP 'inet \K[0-9.]+/[0-9]+' | head -1)
if [ -n "$IPV" ]; then ye "$ARAYUZ = $IPV"
else ky "$ARAYUZ ADRESSİZ — sudo ~/projects/yarisma/araclar/ag_kur.sh"; fi

KOD=$(curl -s -m 4 -o /dev/null -w '%{http_code}' \
      "http://$SUNUCU_IP:$SUNUCU_PORT/api/sunucusaati" 2>/dev/null)
if [ "$KOD" = "200" ]; then ye "sunucu $SUNUCU_IP:$SUNUCU_PORT cevap veriyor (HTTP 200)"
elif [ -n "$KOD" ] && [ "$KOD" != "000" ]; then sa "sunucu HTTP $KOD — ağ tamam, uç noktayı teyit et"
else ky "SUNUCUYA ULAŞILAMIYOR ($SUNUCU_IP:$SUNUCU_PORT)"; fi

bas "YAZILIM"
if python3 -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
    ye "CUDA çalışıyor  ($(python3 -c 'import torch;print(torch.cuda.get_device_name(0))' 2>/dev/null))"
else
    ky "CUDA YOK — YOLO CPU'ya düşer, TELEMETRİ TIKANIR"
    sa "çare:  bash araclar/cuda_duzelt.sh"
fi

MOD="modeller/${DOW_MODEL:-tayarti_v1}.pt"
[ -f "$MOD" ] && ye "model $MOD" || ky "MODEL YOK: $MOD"

id -nG | tr ' ' '\n' | grep -qx dialout && ye "dialout grubu" \
    || ky "dialout grubunda DEĞİLSİN — sudo usermod -aG dialout \$USER (sonra çıkış-giriş)"

if systemctl is-active --quiet ModemManager 2>/dev/null; then
    sa "ModemManager ÇALIŞIYOR — ESP32 portunu bozabilir"
    sa "  sudo systemctl disable --now ModemManager"
else
    ye "ModemManager kapalı"
fi

bas "PORTLAR"
DOLU=$(ss -ltn 2>/dev/null | grep -E ":8765|:8766|:8810" | wc -l)
if [ "$DOLU" = "0" ]; then ye "8765/8766/8810 boş"
else
    ky "PORT DOLU — eski süreç var:"
    ss -ltnp 2>/dev/null | grep -E ":8765|:8766|:8810"
    sa "  for p in \$(pgrep -f drone_yki; pgrep -f yukleyici); do kill -9 \$p; done"
fi

echo
echo "=============================================================="
if [ "$EKSIK" = "0" ]; then
    printf '\033[32m  HER ŞEY HAZIR — uçuş sırasına geçebilirsin.\033[0m\n'
    echo "  1) ~/projects/yarisma/skydagger/baslat_backend.sh"
    echo "  2) ~/projects/yarisma/baslat.sh"
else
    printf '\033[31m  ⛔ %d EKSİK VAR — yukarıdaki ✗ satırlarını gider.\033[0m\n' "$EKSIK"
fi
echo "=============================================================="
exit 0
