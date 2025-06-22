import requests
import urllib.parse
import subprocess
import os
import time
import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# 日志配置
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
            data = base64.b64decode(vmess_str + '=' * (-len(vmess_str) % 4)).decode("utf-8")
            info = json.loads(data)
            host = info.get("add")
            port = info.get("port", "443")
            uuid = info.get("id")
            alterId = info.get("aid", "0")
            network = info.get("net", "tcp")
            vless_url = f"vless://{uuid}@{host}:{port}?encryption=none&alterId={alterId}&type={network}#from_vmess"
            return vless_url
        # 其他协议可按需增加
    except Exception as e:
        logging.warning(f"协议转换失败: {e} | config={config[:60]}")
    return None

def extract_host(config):
    try:
        if config.startswith("vless://"):
            parsed = urllib.parse.urlparse(config)
            host = parsed.netloc.split(":")[0]
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
            return True
        else:
            logging.info(f"Ping失败: {host} | 输出: {out.strip()} | 错误: {err.strip()}")
            return False
    except Exception as e:
        logging.error(f"Ping主机异常: {host} | 错误: {e}")
        return False

def ping_worker(vless):
    host = extract_host(vless)
    if host and ping_host(host):
        return vless
    return None

def main():
    nodes_url = "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt"
    os.makedirs("results", exist_ok=True)
    all_nodes = fetch_unique_nodes(nodes_url)
    vless_nodes = []
    for node in all_nodes:
        vless = to_vless(node)
        if vless:
            vless_nodes.append(vless)
    logging.info(f"优化为vless节点: {len(vless_nodes)} 条")

    valid_nodes = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_vless = {executor.submit(ping_worker, vless): vless for vless in vless_nodes}
        for future in as_completed(future_to_vless):
            result = future.result()
            if result:
                valid_nodes.append(result)

    with open("results/valid_vless_configs.txt", "w") as fout:
        for vless in valid_nodes:
            fout.write(vless + "\n")
    logging.info(f"Ping成功节点: {len(valid_nodes)} 条，已保存到 results/valid_vless_configs.txt")

    # git推送（需配置好权限）
    try:
        os.system("git add results/valid_vless_configs.txt")
        os.system(f'git commit -m "Update valid vless configs {time.strftime("%Y-%m-%d %H:%M:%S")}"')
        os.system("git push")
        logging.info("结果文件已推送到仓库。")
    except Exception as e:
        logging.error(f"推送到GitHub失败: {e}")

if __name__ == "__main__":
    main()
