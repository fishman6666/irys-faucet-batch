# 选择官方 Python 镜像
FROM python:3.10-slim

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y wget gnupg libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libgtk-3-0 libasound2 \
    libxshmfence1 libxext6 libxfixes3 libglib2.0-0 libx11-xcb1 ca-certificates fonts-liberation \
    libappindicator3-1 libu2f-udev xvfb && \
    rm -rf /var/lib/apt/lists/*

# 创建工作目录
WORKDIR /app

# 拷贝代码
COPY . .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright 浏览器依赖和 Chromium
RUN pip install playwright && \
    playwright install chromium

# 容器暴露端口（和 app.py 端口一致）
EXPOSE 10000

# 启动命令
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
