from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor
import time
import threading
from queue import Queue, Empty
import re
import os
import asyncio

from playwright.sync_api import sync_playwright

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

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

def claim_irys_faucet(address, proxy_url, index):
    steps = []
    try:
        steps.append(f"🕐 [{index+1}] 使用代理：{proxy_url or '❌ 代理格式错误'}")
        if not proxy_url:
            steps.append(f"❌ {address} 失败，可重试：无效代理格式")
            return "\n".join(steps)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                proxy={
                    "server": proxy_url
                }
            )
            page = browser.new_page()
            # 打开 faucet 页面
            page.goto("https://irys.xyz/faucet", timeout=60000)
            time.sleep(1.5)

            # 填写钱包地址
            page.fill('input[placeholder="0x..."]', address)
            time.sleep(0.5)

            # 勾选对号（checkbox）
            checkbox = page.query_selector('input[type="checkbox"]')
            if checkbox:
                checkbox.click()
                time.sleep(0.5)

            # 点击领取按钮
            button = page.query_selector('button:has-text("Get $IRYS")')
            if button:
                button.click()
                time.sleep(2.5)
            else:
                steps.append(f"❌ {address} 失败，可重试：未找到领取按钮")
                browser.close()
                return "\n".join(steps)

            # 等待返回/弹窗
            page.wait_for_timeout(2500)
            content = page.content()
            # 简单判断领取结果
            if "Your $IRYS will arrive shortly" in content or "Success" in content:
                steps.append(f"🎉 {address} 领取成功！")
            else:
                # 提取错误弹窗内容
                try:
                    err_msg = page.query_selector("div[role=alert]") or page.query_selector("div.chakra-alert__desc")
                    fail_reason = err_msg.inner_text() if err_msg else "未知错误"
                except Exception as e:
                    fail_reason = f"未知异常: {e}"
                steps.append(f"❌ {address} 失败，可重试：{fail_reason}")
            browser.close()
    except Exception as e:
        steps.append(f"❌ {address} 失败，可重试：{str(e)}")
    return "\n".join(steps)

@app.route('/run', methods=['POST'])
def run():
    # 每次开始领取，清空上次统计的结果文件
    open("results.txt", "w").close()

    data = request.get_json(force=True)
    addresses_raw = data.get('addresses', '')
    proxies_raw = data.get('proxies', '')
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
            with ThreadPoolExecutor(max_workers=6) as executor:  # 不建议太高, playwright 占资源
                futures = [executor.submit(claim_irys_faucet, address, parse_proxy_line(proxies[i]), i) for i, address in enumerate(addresses)]
                for future in futures:
                    try:
                        result = future.result()
                    except Exception as e:
                        result = f"❌ 后台异常: {e}"
                    q.put(result)
                    results.append(result)
            # 保存结果到文件（每次任务都追加一行）
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
        m1 = re.match(r"🎉 (\w{42})", line)
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
