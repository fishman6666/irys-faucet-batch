# 选择官方 Python 镜像
FROM python:3.10-slim

# 安装 Playwright 及 Chromium 所需依赖
RUN apt-get update && \
    apt-get install -y wget gnupg libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libgtk-3-0 libasound2 \
    libxshmfence1 libxext6 libxfixes3 libglib2.0-0 libx11-xcb1 ca-certificates fonts-liberation \
    libappindicator3-1 libu2f-udev xvfb && \
    rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

COPY . .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 这行必不可少！！会自动装chromium，不要只写pip install playwright
RUN python -m playwright install --with-deps chromium

EXPOSE 10000

CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
