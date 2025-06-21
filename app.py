from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor
import time
import threading
from queue import Queue, Empty
import re

from playwright.sync_api import sync_playwright
from playwright._impl._driver import compute_browser_executable_path  # 新增

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

    if not (addresses and proxies):
        return "❌ 参数缺失，请确保地址和代理都填写", 400
    if len(addresses) != len(proxies):
        return "❌ 地址数量与代理数量不一致", 400

    def event_stream():
        q = Queue()

        def task_worker():
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(process_one, i, address, proxies[i]) for i, address in enumerate(addresses)]
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
            chromium_path = compute_browser_executable_path("chromium")  # 新增：获取chromium路径
            browser = p.chromium.launch(
                headless=True,
                executable_path=chromium_path,  # 强制指定chromium
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    f'--proxy-server={proxy_url}' if proxy_url else "",
                ]
            )
            page = browser.new_page()
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            })

            page.goto("https://irys.xyz/faucet", timeout=25000)
            page.wait_for_timeout(2000)

            # 输入钱包地址
            page.fill("input[name='address']", address)
            page.wait_for_timeout(600)

            # 自动勾选Turnstile checkbox（如果需要）
            try:
                checkbox = page.query_selector("input[type=checkbox]")
                if checkbox and checkbox.is_visible():
                    checkbox.click()
                    page.wait_for_timeout(1200)
            except Exception:
                pass  # 没有checkbox则跳过

            # 监听接口响应
            with page.expect_response("**/api/faucet") as resp_info:
                page.click("button[type='submit']")
            resp = resp_info.value

            try:
                data = resp.json()
            except Exception as e:
                browser.close()
                return {"success": False, "message": f"接口返回异常: {e}"}

            browser.close()
            return data  # {"success": bool, "message": str, ...}

    except Exception as e:
        return {"success": False, "message": f"Playwright错误: {e}"}

def process_one(i, address, proxy_line):
    proxy_url = parse_proxy_line(proxy_line)
    steps = []

    steps.append(f"🕐 [{i+1}] 使用代理：{proxy_url or '❌ 代理格式错误'}")
    if not proxy_url:
        steps.append(f"❌ {address} 失败，可重试：无效代理格式")
        return "\n".join(steps)

    steps.append("⏳ [Playwright] 自动操作领取中……")
    result = solve_captcha_with_playwright(address, proxy_url)

    # 接口返回为准
    if result.get("success"):
        steps.append(f"🎉 {address} 领取成功！返回: {result.get('message')}")
    else:
        steps.append(f"❌ {address} 失败，可重试：{result.get('message')}")

    for s in steps:
        print(f"[{i+1}] {s}")

    return "\n".join(steps)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
