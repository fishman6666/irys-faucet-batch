from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor
import time
import threading
from queue import Queue, Empty
import re

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
    client_key = data.get('client_key', '').strip()  # 可留空，无用

    addresses = [a.strip() for a in addresses_raw.strip().split('\n') if a.strip()]
    proxies = [p.strip() for p in proxies_raw.strip().split('\n') if p.strip()]

    if not addresses:
        return "❌ 参数缺失，请确保地址填写", 400
    # proxies 允许为空，也允许数量和地址数量不一致
    # 如果有代理就一一对应，没有就全部用本地

    def event_stream():
        q = Queue()

        def task_worker():
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                # zip_longest自动填None
                from itertools import zip_longest
                futures = [executor.submit(process_one, i, address, proxies[i] if i < len(proxies) else None)
                           for i, address in enumerate(addresses)]
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
    if not proxy_line:
        return None
    try:
        parts = proxy_line.strip().split(":")
        if len(parts) == 5 and parts[-1].upper() == "SOCKS5":
            host, port, user, pwd, _ = parts
            return f"socks5://{user}:{pwd}@{host}:{port}"
        elif len(parts) == 4:
            host, port, user, pwd = parts
            return f"socks5://{user}:{pwd}@{host}:{port}"
        else:
            return None
    except Exception:
        return None

def solve_captcha_with_playwright(address, proxy_url):
    try:
        chromium_path = "/opt/render/.cache/ms-playwright/chromium-1169/chrome-linux/chrome"
        from pathlib import Path
        if not Path(chromium_path).exists():
            import glob
            chrome_glob = glob.glob("/opt/render/.cache/ms-playwright/chromium-*/chrome-linux/chrome")
            if chrome_glob:
                chromium_path = chrome_glob[0]
        with sync_playwright() as p:
            args = ["--no-sandbox", "--disable-dev-shm-usage"]
            if proxy_url:
                args.append(f'--proxy-server={proxy_url}')
            browser = p.chromium.launch(
                headless=True,
                executable_path=chromium_path,
                args=args
            )
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            })

            page.goto("https://irys.xyz/faucet", timeout=25000)
            page.wait_for_timeout(2000)
            page.fill("input[name='address']", address)
            page.wait_for_timeout(600)
            try:
                checkbox = page.query_selector("input[type=checkbox]")
                if checkbox and checkbox.is_visible():
                    checkbox.click()
                    page.wait_for_timeout(1200)
            except Exception:
                pass

            with page.expect_response("**/api/faucet") as resp_info:
                page.click("button[type='submit']")
            resp = resp_info.value

            try:
                data = resp.json()
            except Exception as e:
                browser.close()
                return {"success": False, "message": f"接口返回异常: {e}"}

            browser.close()
            return data

    except Exception as e:
        return {"success": False, "message": f"Playwright错误: {e}"}

def process_one(i, address, proxy_line):
    proxy_url = parse_proxy_line(proxy_line) if proxy_line else None
    steps = []

    steps.append(f"🕐 [{i+1}] 使用代理：{proxy_url or '无（本机直连）'}")
    # 允许无代理直接跑
    steps.append("⏳ [Playwright] 自动操作领取中……")
    result = solve_captcha_with_playwright(address, proxy_url)

    if result.get("success"):
        steps.append(f"🎉 {address} 领取成功！返回: {result.get('message')}")
    else:
        steps.append(f"❌ {address} 失败，可重试：{result.get('message')}")

    for s in steps:
        print(f"[{i+1}] {s}")

    return "\n".join(steps)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
