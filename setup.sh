#!/usr/bin/env bash

set -e

VENV_DIR="libr"

echo "Python kontrol ediliyor..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "HATA: python3 bulunamadı."
    exit 1
fi

echo "Python sürümü:"
python3 --version

if [ -d "$VENV_DIR" ]; then
    echo "Mevcut sanal ortam bulundu: $VENV_DIR"
else
    echo "Sanal ortam oluşturuluyor..."
    python3 -m venv "$VENV_DIR"
fi

echo "Sanal ortam aktif ediliyor..."
source "$VENV_DIR/bin/activate"

echo "pip güncelleniyor..."
python -m pip install --upgrade pip

echo "Bağımlılıklar kuruluyor..."
python -m pip install -r requirements.txt

echo
echo "Kurulum tamamlandı."
echo
echo "Projeyi çalıştırmak için:"
echo "  source $VENV_DIR/bin/activate"
echo "  python main.py"
