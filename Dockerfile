# 使用 NVIDIA 官方支援 ARM64 的基礎鏡像 (Grace CPU 必備)
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# 設定環境變數
ENV DEBIAN_FRONTEND=noninteractive

# 針對 ARM64 安裝 Python 3.10 與必要依賴 (含編譯環境)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    curl \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 確保 pip 是最新的並安裝依賴
# 針對 ARM64，有些套件會從源碼編譯，因此需要 build-essential
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

# 複製專案代碼
COPY . .

# 執行權限
RUN chmod +x start.sh

# 預設執行指令 (使用 python3 並強制覆蓋舊檔)
CMD ["python3", "-m", "src.cli", "--input", "input_dir", "--output", "output_dir", "--workers", "8", "--force"]
