from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import threading
from queue import Queue, Empty
import json
import re
import os

# ！！！注意这里新增
from playwright.sync_api import sync_playwright

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run', methods=['POST'])
def run():
    open("results.txt", "w").close()

    data = request.get_json(force=True)
    addresses_raw = data.get('addresses', '')
    proxies_raw = data.get('proxies', '')
    client_key = data.get('client_key', '').strip()

    addresses = [a.strip() for a in addresses_raw.strip().split('\n') if a.strip()]
    proxies = [p.strip() for p in proxies_raw.strip().split('\n') if p.strip()]

    if not (addresses and proxies and client_key):
        return "❌ 参数缺失，请确保地址、代理和 clientKey 都填写", 400
    if len(addresses) != len(proxies):
        return "❌ 地址数量与代理数量不一致", 400

    def event_stream():
        q = Queue()

        def task_worker():
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(process_one, i, address, proxies[i], client_key) for i, address in enumerate(addresses)]
                for future in futures:
                    try:
                        result = future.result()
                    except Exception as e:
                        result = f"❌ 后台异常: {e}"
                    q.put(result)
                    results.append(result)
            with open("results.txt", "a", encoding="utf-8") as f:
                for r in results:
                    for line in r.strip().split('\n'):
                        if line.startswith("🎉") or line.startswith("❌"):
                            f.write(line + "\n")
            q.put(None)

        threading.Thread(target=task_worker, daemon=True).start()

        while True:
            try:
                result = q.get(timeout=5)
                if result is None:
                    break
                yield f"data: {result}\n\n"
            except Empty:
                yield f"data: [心跳] {time.strftime('%H:%M:%S')}\n\n"

    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/results')
def results():
    try:
        with open("results.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        lines = []
    success = []
    fail_dict = {}
    success_addr = set()

    for line in lines:
        line = line.strip()
        m1 = re.match(r"🎉 (\w{42}) ", line)
        if m1:
            addr = m1.group(1)
            success.append(line)
            success_addr.add(addr)
        m2 = re.match(r"❌ (\w{42}) 失败，可重试：(.*)", line)
        if m2:
            addr = m2.group(1)
            reason = m2.group(2)
            if addr not in success_addr:
                fail_dict[addr] = f"❌ {addr} 失败，可重试：{reason}"

    resp = "\n".join(success + list(fail_dict.values()))
    return resp

def parse_proxy_line(proxy_line):
    try:
        parts = proxy_line.strip().split(":")
        if len(parts) == 5 and parts[-1].upper() == "SOCKS5":
            host, port, user, pwd, _ = parts
        elif len(parts) == 4:
            host, port, user, pwd = parts
        else:
            return None
        return f"socks5://{user}:{pwd}@{host}:{port}"
    except Exception:
        return None

def solve_captcha_with_playwright(address, proxy_url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path="/usr/bin/google-chrome-stable",  # Render 部署用 Chrome 路径
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    f'--proxy-server={proxy_url}' if proxy_url else "",
                ]
            )
            page = browser.new_page()
            # 访问领水页面，这里可根据实际需求修改
            page.goto("https://irys.xyz/faucet")
            time.sleep(2)
            # 这里需要根据你实际情况自动输入钱包地址、点按钮（自己补充！）
            browser.close()
        return "TODO: CAPTCHA/操作完成！"
    except Exception as e:
        return f"Playwright错误: {e}"

def process_one(i, address, proxy_line, client_key):
    proxy_url = parse_proxy_line(proxy_line)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    steps = []

    steps.append(f"🕐 [{i+1}] 使用代理：{proxy_url or '❌ 代理格式错误'}")
    if not proxy_url:
        steps.append(f"❌ {address} 失败，可重试：无效代理格式")
        return "\n".join(steps)

    # Playwright自动打码和自动领水操作（需要你根据实际页面实现！）
    steps.append("⏳ [Playwright] 打开网页准备操作")
    captcha_result = solve_captcha_with_playwright(address, proxy_url)
    steps.append(f"[Playwright] 返回: {captcha_result}")

    # 演示，等你完善后端具体交互
    if "错误" not in captcha_result:
        steps.append(f"🎉 {address} 领取成功！（仅演示）")
    else:
        steps.append(f"❌ {address} 失败，可重试：{captcha_result}")

    for s in steps:
        print(f"[{i+1}] {s}")

    return "\n".join(steps)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
