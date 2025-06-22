import requests
import urllib.parse
import subprocess
import os
import time
import base64
import json
import logging
import re
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

# 日志配置
os.makedirs("results", exist_ok=True)
logging.basicConfig(
    filename="results/node_test.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def fetch_unique_nodes(url):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        unique_lines = set(line.strip() for line in res.text.splitlines() if line.strip())
        logging.info(f"成功获取节点，总数: {len(unique_lines)}")
        return list(unique_lines)
    except Exception as e:
        logging.error(f"获取节点失败: {e}")
        return []

def to_vless(config):
    try:
        config = config.strip()
        if config.startswith("vless://"):
            return config
        elif config.startswith("vmess://"):
            vmess_str = config[8:]
            padded = vmess_str + '=' * (-len(vmess_str) % 4)
            data = base64.b64decode(padded).decode("utf-8")
            info = json.loads(data)
            host = info.get("add")
            port = info.get("port", "443")
            uuid = info.get("id")
            network = info.get("net", "tcp")
            # 组装参数
            params = []
            params.append("encryption=none")
            params.append(f"type={network}")
            if info.get("host"):
                params.append(f"host={info.get('host')}")
            if info.get("sni"):
                params.append(f"sni={info.get('sni')}")
            if info.get("path"):
                params.append(f"path={info.get('path')}")
            if info.get("alpn"):
                params.append(f"alpn={info.get('alpn')}")
            if info.get("serviceName"):
                params.append(f"serviceName={info.get('serviceName')}")
            param_str = "&".join(params)
            tag = info.get("ps", "from_vmess")
            vless_url = f"vless://{uuid}@{host}:{port}?{param_str}#{tag}"
            return vless_url
    except Exception as e:
        logging.warning(f"协议转换失败: {e} | config={config[:60]}")
    return None

def is_valid_vless_url(vless_url):
    # 校验vless://uuid@host:port?xxx#xxx
    pattern = re.compile(r"^vless://[0-9a-fA-F\-]{36}@([\w\.\-]+):(\d+)\?.+#")
    match = pattern.match(vless_url)
    if not match:
        return False
    host, port = match.groups()
    # 校验端口
    try:
        port = int(port)
        if not (0 < port < 65536):
            return False
    except Exception:
        return False
    # 校验host为合法IP或域名
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        # 尝试校验为域名
        if re.match(r"^[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}$", host):
            return True
    return False

def extract_host(config):
    try:
        if config.startswith("vless://"):
            parsed = urllib.parse.urlparse(config)
            netloc = parsed.netloc
            if "@" in netloc:
                netloc = netloc.split("@", 1)[1]
            host = netloc.split(":", 1)[0]
            return host
    except Exception as e:
        logging.warning(f"提取host失败: {e} | config={config[:60]}")
    return None

def ping_host(host, timeout=5, count=3):
    try:
        proc = subprocess.Popen(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        out, err = proc.communicate(timeout=timeout + 2)
        if proc.returncode == 0:
            logging.info(f"Ping成功: {host}")
            return True, out
        else:
            logging.info(f"Ping失败: {host} | 输出: {out.strip()} | 错误: {err.strip()}")
            return False, out + err
    except Exception as e:
        logging.error(f"Ping主机异常: {host} | 错误: {e}")
        return False, str(e)

def ping_worker(vless):
    host = extract_host(vless)
    if host:
        ok, ping_log = ping_host(host)
        return vless, host, ok, ping_log
    return vless, None, False, "无法提取host"

def main():
    nodes_url = "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt"
    all_nodes = fetch_unique_nodes(nodes_url)
    vless_nodes = []
    for node in all_nodes:
        vless = to_vless(node)
        if vless and is_valid_vless_url(vless):
            vless_nodes.append(vless)
    logging.info(f"优化为有效vless节点: {len(vless_nodes)} 条")

    valid_nodes = []
    ping_results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_vless = {executor.submit(ping_worker, vless): vless for vless in vless_nodes}
        for future in as_completed(future_to_vless):
            vless, host, ok, ping_log = future.result()
            status = "OK" if ok else "FAILED"
            ping_results.append(f"Node: {vless}\nHost: {host}, Status: {status}\nPing log:\n{ping_log}\n{'='*40}\n")
            if ok:
                valid_nodes.append(vless)

    # 总是生成 ping_test_results.txt
    with open("results/ping_test_results.txt", "w") as fout:
        fout.write(f"Ping Test Results - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fout.write("="*50 + "\n")
        if ping_results:
            fout.writelines(ping_results)
        else:
            fout.write("无可用节点或无可用结果。\n")

    with open("results/valid_vless_configs.txt", "w") as fout:
        for vless in valid_nodes:
            fout.write(vless + "\n")
    logging.info(f"Ping成功节点: {len(valid_nodes)} 条，已保存到 results/valid_vless_configs.txt")

if __name__ == "__main__":
    main()
