# 选择官方 Python 镜像
FROM python:3.10-slim

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y wget gnupg libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libgtk-3-0 libasound2 \
    libxshmfence1 libxext6 libxfixes3 libglib2.0-0 libx11-xcb1 ca-certificates fonts-liberation \
    libappindicator3-1 libu2f-udev xvfb && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# 这行就够了，requirements.txt 里有 playwright 就能安装
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Chromium 浏览器
RUN playwright install chromium

EXPOSE 10000

CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
