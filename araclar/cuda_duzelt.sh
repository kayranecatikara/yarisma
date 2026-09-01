#!/usr/bin/env bash
# CUDA "unknown error" düzeltmesi — nvidia_uvm modülünü yeniden yükler.
# YAŞANDI (2026-09-01): nvidia-smi çalışıyordu, sürücü sağlamdı, ama
# torch "CUDA unknown error" veriyordu ve `lsmod` nvidia_uvm'i göstermedi.
# Sonuç: YOLO işlemcide koştu, ana güdüm döngüsü ~5 s'ye düştü ve
# TELEMETRİ DE onunla birlikte durdu (araç konumu 5 s'de bir geliyordu).
set -u
echo "== modul durumu (once) =="; lsmod | grep -c nvidia_uvm || true
echo k | sudo -S modprobe nvidia_uvm 2>&1 | grep -v '^\[sudo' || true
sleep 1
echo "== modul durumu (sonra) =="; lsmod | grep nvidia_uvm || echo "  YUKLENEMEDI"
echo "== torch =="
python3 -c "import torch; print('  CUDA:', torch.cuda.is_available()); print('  cihaz:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')" 2>&1 | grep -v Warning
