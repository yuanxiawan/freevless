import requests
import urllib.parse
import socket
import os
import time
import base64
import json
import logging
import re
import ipaddress
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

# 日志配置
os.makedirs("results", exist_ok=True)
logging.basicConfig(
    filename="results/node_test.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def fetch_unique_nodes(url, sample_count=50):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        unique_lines = list(set(line.strip() for line in res.text.splitlines() if line.strip()))
        logging.info(f"成功获取节点，总数: {len(unique_lines)}")
        # 随机采样 sample_count 条
        if len(unique_lines) > sample_count:
            sampled = random.sample(unique_lines, sample_count)
        else:
            sampled = unique_lines
        logging.info(f"本次随机采样节点数: {len(sampled)}")
        return sampled
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
    pattern = re.compile(r"^vless://[0-9a-fA-F\-]{36}@([\w\.\-]+):(\d+)\?.+#")
    match = pattern.match(vless_url)
    if not match:
        return False
    host, port = match.groups()
    try:
        port = int(port)
        if not (0 < port < 65536):
            return False
    except Exception:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        if re.match(r"^[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}$", host):
            return True
    return False

def extract_host_port(config):
    # 返回 host, port
    try:
        if config.startswith("vless://"):
            parsed = urllib.parse.urlparse(config)
            netloc = parsed.netloc
            if "@" in netloc:
                netloc = netloc.split("@", 1)[1]
            parts = netloc.split(":", 1)
            host = parts[0]
            port = "443"  # 默认端口
            if len(parts) > 1 and parts[1].isdigit():
                port = parts[1]
            else:
                # 尝试从 query 里取 port
                q = urllib.parse.parse_qs(parsed.query)
                if "port" in q and q["port"][0].isdigit():
                    port = q["port"][0]
            return host, port
    except Exception as e:
        logging.warning(f"提取host/port失败: {e} | config={config[:60]}")
    return None, None

def tcp_connect(host, port, timeout=5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, "TCP连接成功"
    except Exception as e:
        return False, f"TCP连接失败: {e}"

def connect_worker(vless):
    host, port = extract_host_port(vless)
    if host and port:
        ok, log = tcp_connect(host, port)
        return vless, host, port, ok, log
    return vless, None, None, False, "无法提取host或port"

def main():
    nodes_url = "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt"
    all_nodes = fetch_unique_nodes(nodes_url, sample_count=50)
    vless_nodes = []
    for node in all_nodes:
        vless = to_vless(node)
        if vless and is_valid_vless_url(vless):
            vless_nodes.append(vless)
    logging.info(f"优化为有效vless节点: {len(vless_nodes)} 条")

    valid_nodes = []
    connect_results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_vless = {executor.submit(connect_worker, vless): vless for vless in vless_nodes}
        for future in as_completed(future_to_vless):
            vless, host, port, ok, logtxt = future.result()
            status = "OK" if ok else "FAILED"
            connect_results.append(f"Node: {vless}\nHost: {host}, Port: {port}, Status: {status}\nTCP log:\n{logtxt}\n{'='*40}\n")
            if ok:
                valid_nodes.append(vless)

    with open("results/ping_test_results.txt", "w") as fout:
        fout.write(f"TCP Connect Test Results - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fout.write("="*50 + "\n")
        if connect_results:
            fout.writelines(connect_results)
        else:
            fout.write("无可用节点或无可用结果。\n")

    with open("results/valid_vless_configs.txt", "w") as fout:
        for vless in valid_nodes:
            fout.write(vless + "\n")
    logging.info(f"TCP连接成功节点: {len(valid_nodes)} 条，已保存到 results/valid_vless_configs.txt")

if __name__ == "__main__":
    main()
