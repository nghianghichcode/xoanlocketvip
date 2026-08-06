#!/bin/bash
# ================================================
#  Locket Gold Bot - One-command setup & run
#  Dùng: bash run.sh
# ================================================
cd "$(dirname "$0")"

echo "======================================"
echo "   🚀 Locket Gold Bot - Auto Setup"
echo "======================================"

# ---------- Kiểm tra Python ----------
if ! command -v python3 &>/dev/null; then
    echo "❌ Chưa có Python3. Đang cài..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip python3-venv -qq
    elif command -v yum &>/dev/null; then
        sudo yum install -y python3 python3-pip -q
    else
        echo "❌ Không tự cài được Python. Hãy cài python3 thủ công rồi chạy lại."
        exit 1
    fi
fi

PYTHON_VER=$(python3 --version 2>&1)
echo "✅ $PYTHON_VER"

# ---------- Tạo Virtual Environment ----------
if [ ! -d "venv" ]; then
    echo "📦 Tạo môi trường ảo..."
    python3 -m venv venv
fi

# ---------- Cài thư viện ----------
echo "📥 Cài thư viện từ requirements.txt..."
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
echo "✅ Cài thư viện xong!"

# ---------- Kiểm tra config ----------
# Đọc .env nếu có, nếu không thì dùng giá trị trong config.py
if [ -f ".env" ]; then
    source .env
fi

echo ""
echo "======================================"
echo "✅ Setup hoàn tất! Đang khởi động bot..."
echo "======================================"
echo ""

# Dừng tiến trình cũ nếu có
pkill -f "main.py" 2>/dev/null
sleep 1

# Chạy bot
./venv/bin/python3 main.py
