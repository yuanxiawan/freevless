import requests
import urllib.parse
import subprocess
import os
import time
import re
import base64
import json

def extract_host_and_proto(config):
    config = config.strip()
    if config.startswith("vless://"):
        try:
            parsed = urllib.parse.urlparse(config)
            host = parsed.netloc.split(":")[0]
            return "vless", host
        except Exception:
            return None, None
    elif config.startswith("vmess://"):
        try:
            vmess_str = config[8:]
            data = base64.b64decode(vmess_str + '=' * (-len(vmess_str) % 4)).decode("utf-8")
            info = json.loads(data)
            host = info.get("add")
            return "vmess", host
        except Exception:
            return None, None
    elif '@' in config:
        host = config.split('@')[-1].split(':')[0]
        return "simple", host
    else:
        return None, None

def ping_test(host, timeout=5, ping_count=4):
    try:
        proc = subprocess.Popen(
            ["ping", "-c", str(ping_count), "-W", "1", host],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode == 0
    except Exception:
        return False

def get_node_configs(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        lines = [line.strip() for line in response.text.splitlines() if line.strip()]
        return lines
    except Exception as e:
        print(f"Error fetching nodes: {e}")
        return []

def main():
    nodes_url = "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt"
    all_nodes = get_node_configs(nodes_url)
    valid_nodes = []
    os.makedirs("results", exist_ok=True)
    with open("results/ping_test_results.txt", "w") as fout:
        fout.write(f"Ping Test Results - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fout.write("="*50 + "\n")
        for config in all_nodes:
            proto, host = extract_host_and_proto(config)
            if not host:
                fout.write(f"Node: {config[:60]}... Status: SKIPPED\n")
                continue
            ok = ping_test(host)
            status = "OK" if ok else "FAILED"
            fout.write(f"Node: {config[:60]}... Protocol: {proto}, Host: {host}, Status: {status}\n")
            if ok:
                # 只要 ping 通，就保存 config（即原始节点信息）
                valid_nodes.append(config)
    with open("results/valid_nodes.txt", "w") as fvalid:
        for c in valid_nodes:
            fvalid.write(f"{c}\n")
    print(f"已保存可用节点 {len(valid_nodes)} 条到 results/valid_nodes.txt")

if __name__ == "__main__":
    main()
