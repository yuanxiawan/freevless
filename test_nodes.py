import requests
import urllib.parse
import subprocess
import os
import time
import re
import psutil
import base64
import json

def parse_vless_url(vless_url):
    try:
        parsed = urllib.parse.urlparse(vless_url)
        if not parsed.scheme == "vless":
            return None
        host_port = parsed.netloc.split(":")
        host = host_port[0]
        return {
            "protocol": "vless",
            "host": host,
            "original_url": vless_url
        }
    except Exception as e:
        print(f"Error parsing VLESS URL: {str(e)}")
        return None

def parse_vmess_url(vmess_url):
    try:
        parsed = urllib.parse.urlparse(vmess_url)
        if not parsed.scheme == "vmess":
            return None
        base64_config = parsed.netloc
        try:
            config_json = base64.b64decode(base64_config).decode("utf-8")
            config = json.loads(config_json)
            host = config.get("add")
            return {
                "protocol": "vmess",
                "host": host,
                "original_url": vmess_url
            }
        except (base64.binascii.Error, json.JSONDecodeError):
            return None
    except Exception as e:
        print(f"Error parsing VMess URL: {str(e)}")
        return None

def parse_simple_host(config):
    """兼容 uuid@ip[:port] 简易格式"""
    try:
        if '@' in config:
            host_port = config.split('@')[-1]
            host = host_port.split(':')[0]
            return host
        return None
    except Exception:
        return None

def kill_process_and_children(pid):
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

def ping_test(host, timeout=5, ping_count=4):
    print(f"Starting ping test for host: {host}")
    ping_process = None
    try:
        ping_process = subprocess.Popen(
            [
                "ping",
                "-c", str(ping_count),
                "-W", "1",
                host
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Ping process started with PID: {ping_process.pid}")
        try:
            stdout, stderr = ping_process.communicate(timeout=timeout)
            if ping_process.returncode == 0:
                print(f"Ping test succeeded for {host}")
                return True
            else:
                print(f"Ping test failed for {host}: {stderr}")
                return False
        except subprocess.TimeoutExpired:
            print(f"Ping test timed out for {host}")
            return False
    except Exception as e:
        print(f"Error during ping test for {host}: {str(e)}")
        return False
    finally:
        if ping_process and ping_process.poll() is None:
            try:
                print(f"Terminating ping process with PID: {ping_process.pid}")
                ping_process.terminate()
                ping_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                print(f"Forcing kill of ping process with PID: {ping_process.pid}")
                kill_process_and_children(ping_process.pid)
            except Exception as e:
                print(f"Error terminating ping process: {str(e)}")
        print(f"Finished ping test for host: {host}")

def get_node_configs():
    config_source = os.getenv("NODE_CONFIG_SOURCE", "single_url")
    config_urls = os.getenv("NODE_CONFIG_URLS", "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt").split(",")
    local_files = os.getenv("NODE_CONFIG_FILES", "").split(",")
    node_configs = []
    if config_source == "single_url":
        print(f"Fetching nodes from single URL: {config_urls[0]}")
        try:
            response = requests.get(config_urls[0], timeout=10)
            response.raise_for_status()
            node_configs.extend(response.text.splitlines())
            print(f"Downloaded {len(node_configs)} nodes from {config_urls[0]}")
        except requests.RequestException as e:
            print(f"Error fetching nodes from {config_urls[0]}: {str(e)}")
    elif config_source == "multiple_urls":
        for url in config_urls:
            if not url.strip():
                continue
            print(f"Fetching nodes from URL: {url}")
            try:
                response = requests.get(url.strip(), timeout=10)
                response.raise_for_status()
                node_configs.extend(response.text.splitlines())
                print(f"Downloaded {len(response.text.splitlines())} nodes from {url}")
            except requests.RequestException as e:
                print(f"Error fetching nodes from {url}: {str(e)}")
    elif config_source == "local_files":
        for file_path in local_files:
            if not file_path.strip():
                continue
            print(f"Reading nodes from local file: {file_path}")
            try:
                if os.path.exists(file_path):
                    with open(file_path, "r") as f:
                        node_configs.extend(f.read().splitlines())
                    print(f"Read {len(node_configs)} nodes from {file_path}")
                else:
                    print(f"Local file not found: {file_path}")
            except Exception as e:
                print(f"Error reading local file {file_path}: {str(e)}")
    node_configs = list(dict.fromkeys([config.strip() for config in node_configs if config.strip()]))
    return node_configs

def main():
    os.makedirs("results", exist_ok=True)
    output_file = "results/ping_test_results.txt"
    valid_configs_file = "results/valid_vless_configs.txt"
    start_time = time.time()
    print("Fetching node configurations...")
    node_configs = get_node_configs()
    print(f"Total unique nodes fetched: {len(node_configs)}")
    valid_configs = []
    with open(output_file, "w") as f:
        f.write(f"Ping Test Results - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 50 + "\n")
        for config in node_configs:
            if not config:
                continue
            node_info = None
            if config.startswith("vless://"):
                node_info = parse_vless_url(config)
            elif config.startswith("vmess://"):
                node_info = parse_vmess_url(config)
            elif '@' in config:  # 兼容 uuid@ip[:port] 格式
                host = parse_simple_host(config)
                if host:
                    node_info = {"protocol": "simple", "host": host, "original_url": config}
            else:
                f.write(f"Node: {config[:50]}... Status: SKIPPED (Unsupported protocol)\n")
                print(f"Skipping unsupported protocol: {config[:50]}...")
                continue
            if node_info:
                host = node_info["host"]
                ping_result = ping_test(host)
                status = "OK" if ping_result else "FAILED"
                f.write(
                    f"Node: {config[:50]}... Protocol: {node_info['protocol'].upper()}, "
                    f"Host: {host}, Status: {status}\n"
                )
                print(f"Tested host {host}: {status}")
                if ping_result:
                    valid_configs.append(config)
            else:
                f.write(f"Node: {config[:50]}... Status: INVALID\n")
                print(f"Invalid node configuration: {config[:50]}...")
    with open(valid_configs_file, "w") as f:
        for config in valid_configs:
            f.write(f"{config}\n")
    print(f"Saved {len(valid_configs)} valid configurations to {valid_configs_file}")
    print(f"Script completed successfully. Total execution time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()
