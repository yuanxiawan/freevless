import requests
import urllib.parse
import subprocess
import json
import os
import time
import uuid
import base64
import re
import signal
import psutil

def parse_vless_url(vless_url):
    """解析 VLESS URL 获取主机、端口、用户 ID 和其他参数"""
    try:
        parsed = urllib.parse.urlparse(vless_url)
        if not parsed.scheme == "vless":
            return None
        user_id = parsed.path.strip("@")
        host_port = parsed.netloc.split(":")
        host = host_port[0]
        port = host_port[1] if len(host_port) > 1 else "443"
        query = urllib.parse.parse_qs(parsed.query)
        encryption = query.get("encryption", ["none"])[0]
        security = query.get("security", ["tls"])[0]
        return {
            "protocol": "vless",
            "user_id": user_id,
            "host": host,
            "port": port,
            "encryption": encryption,
            "security": security,
            "original_url": vless_url
        }
    except Exception as e:
        print(f"Error parsing VLESS URL: {str(e)}")
        return None

def parse_vmess_url(vmess_url):
    """解析 VMess URL 获取主机、端口、用户 ID 和其他参数"""
    try:
        parsed = urllib.parse.urlparse(vmess_url)
        if not parsed.scheme == "vmess":
            return None
        base64_config = parsed.netloc
        try:
            config_json = base64.b64decode(base64_config).decode("utf-8")
            config = json.loads(config_json)
            return {
                "protocol": "vmess",
                "user_id": config.get("id"),
                "host": config.get("add"),
                "port": config.get("port", "443"),
                "encryption": config.get("scy", "auto"),
                "network": config.get("net", "tcp"),
                "security": config.get("tls", "none"),
                "original_url": vmess_url
            }
        except (base64.binascii.Error, json.JSONDecodeError):
            return None
    except Exception as e:
        print(f"Error parsing VMess URL: {str(e)}")
        return None

def infer_location(host):
    """根据主机名推断地理位置"""
    host = host.lower()
    location_patterns = {
        "asia": [r"\b(jp|japan|hk|hongkong|sg|singapore|kr|korea|tw|taiwan|cn|china)\b"],
        "north_america": [r"\b(us|usa|ca|canada)\b"],
        "europe": [r"\b(uk|gb|de|germany|fr|france|nl|netherlands|se|sweden|it|italy|es|spain)\b"],
        "oceania": [r"\b(au|australia|nz|newzealand)\b"],
        "south_america": [r"\b(br|brazil|ar|argentina|cl|chile)\b"],
        "africa": [r"\b(za|southafrica|ng|nigeria|ke|kenya)\b"]
    }
    for region, patterns in location_patterns.items():
        for pattern in patterns:
            if re.search(pattern, host):
                return region
    return "unknown"

def create_xray_config(node_info, config_path):
    """生成 Xray 配置文件"""
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 1080,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            }
        ],
        "outbounds": [
            {
                "protocol": node_info["protocol"],
                "settings": {},
                "streamSettings": {
                    "network": node_info.get("network", "tcp"),
                    "security": node_info["security"],
                    "tlsSettings": {} if node_info["security"] == "tls" else None
                }
            }
        ]
    }
    if node_info["protocol"] == "vless":
        config["outbounds"][0]["settings"]["vnext"] = [
            {
                "address": node_info["host"],
                "port": int(node_info["port"]),
                "users": [
                    {
                        "id": node_info["user_id"],
                        "encryption": node_info["encryption"]
                    }
                ]
            }
        ]
    elif node_info["protocol"] == "vmess":
        config["outbounds"][0]["settings"]["vnext"] = [
            {
                "address": node_info["host"],
                "port": int(node_info["port"]),
                "users": [
                    {
                        "id": node_info["user_id"],
                        "security": node_info["encryption"]
                    }
                ]
            }
        ]
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

def kill_process_and_children(pid):
    """强制终止进程及其子进程"""
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

def test_node(node_info, timeout=5):
    """测试节点连通性、延迟和丢包率"""
    if not node_info:
        return "INVALID", None, None
    config_path = f"config_{uuid.uuid4()}.json"
    xray_process = None
    print(f"Starting test for node: {node_info['host']}:{node_info['port']}")
    try:
        create_xray_config(node_info, config_path)
        xray_process = subprocess.Popen(
            ["./xray/xray", "run", "-c", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # 为 Linux 创建进程组
        )
        time.sleep(1)
        print(f"Xray process started with PID: {xray_process.pid}")

        start_time = time.time()
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-x", "socks5://127.0.0.1:1080",
                    "https://www.google.com",
                    "--connect-timeout", str(timeout),
                    "--max-time", str(timeout),
                    "--silent"
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 1  # 额外超时保护
            )
            latency = (time.time() - start_time) * 1000
            status = "OK" if result.returncode == 0 else "FAILED"
            print(f"Connectivity test completed: {status}, Latency: {latency:.2f} ms")
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            status = "FAILED"
            latency = None
            print("Connectivity test failed or timed out")

        packet_loss = None
        if status == "OK":
            try:
                ping_count = 5
                result = subprocess.run(
                    [
                        "ping",
                        "-c", str(ping_count),
                        "-W", "1",
                        node_info["host"]
                    ],
                    capture_output=True,
                    text=True,
                    timeout=ping_count * 2
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "packet loss" in line:
                            loss_str = line.split("%")[0].split()[-1]
                            packet_loss = float(loss_str)
                            break
                    print(f"Packet loss test completed: {packet_loss:.1f}%")
            except (subprocess.SubprocessError, subprocess.TimeoutExpired):
                packet_loss = None
                print("Packet loss test failed or timed out")

        return status, latency, packet_loss
    except Exception as e:
        print(f"Error testing node {node_info['host']}:{node_info['port']}: {str(e)}")
        return "ERROR", None, None
    finally:
        if xray_process:
            try:
                print(f"Terminating Xray process with PID: {xray_process.pid}")
                os.killpg(os.getpgid(xray_process.pid), signal.SIGTERM)  # 终止进程组
                xray_process.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                print(f"Forcing kill of Xray process with PID: {xray_process.pid}")
                kill_process_and_children(xray_process.pid)
            except Exception as e:
                print(f"Error terminating Xray process: {str(e)}")
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
                print(f"Removed temporary config file: {config_path}")
            except Exception as e:
                print(f"Error removing config file {config_path}: {str(e)}")
        print(f"Finished test for node: {node_info['host']}:{node_info['port']}")

def create_grouped_config(nodes, group_name, output_path):
    """为分组生成 Xray 配置文件"""
    xray_config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 1080,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            }
        ],
        "outbounds": []
    }
    for node in nodes:
        outbound = {
            "protocol": node["protocol"],
            "settings": {
                "vnext": [
                    {
                        "address": node["host"],
                        "port": int(node["port"]),
                        "users": [
                            {
                                "id": node["user_id"],
                                "encryption": node["encryption"]
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "network": node.get("network", "tcp"),
                "security": node["security"],
                "tlsSettings": {} if node["security"] == "tls" else None
            },
            "tag": f"{node['protocol']}-{node['host']}:{node['port']}",
            "metrics": node["metrics"]
        }
        xray_config["outbounds"].append(outbound)
    
    with open(output_path, "w") as f:
        json.dump(xray_config, f, indent=2)

def main():
    config_url = "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt"
    os.makedirs("results", exist_ok=True)
    output_file = "results/vless_test_results.txt"
    valid_nodes_file = "results/valid_nodes.json"
    
    start_time = time.time()
    print("Downloading node configurations...")
    try:
        response = requests.get(config_url, timeout=10)
        response.raise_for_status()
        node_configs = response.text.splitlines()
        print(f"Downloaded {len(node_configs)} node configurations")
    except requests.RequestException as e:
        with open(output_file, "w") as f:
            f.write(f"Error downloading node configs: {str(e)}\n")
        print(f"Error downloading node configs: {str(e)}")
        return

    valid_nodes = []
    with open(output_file, "w") as f:
        f.write(f"Node Test Results - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 50 + "\n")
        for config in node_configs:
            config = config.strip()
            if not config:
                continue
            node_info = None
            if config.startswith("vless://"):
                node_info = parse_vless_url(config)
            elif config.startswith("vmess://"):
                node_info = parse_vmess_url(config)
            else:
                f.write(f"Node: {config[:50]}... Status: SKIPPED (Unsupported protocol)\n")
                print(f"Skipping unsupported protocol: {config[:50]}...")
                continue
            
            if node_info:
                status, latency, packet_loss = test_node(node_info)
                latency_str = f"{latency:.2f} ms" if latency else "N/A"
                packet_loss_str = f"{packet_loss:.1f}%" if packet_loss is not None else "N/A"
                f.write(
                    f"Node: {config[:50]}... Protocol: {node_info['protocol'].upper()}, "
                    f"Status: {status}, Latency: {latency_str}, Packet Loss: {packet_loss_str}\n"
                )
                if status == "OK":
                    node_info["metrics"] = {
                        "latency": latency,
                        "packet_loss": packet_loss if packet_loss is not None else 100
                    }
                    node_info["location"] = infer_location(node_info["host"])
                    valid_nodes.append(node_info)
            else:
                f.write(f"Node: {config[:50]}... Status: INVALID\n")
                print(f"Invalid node configuration: {config[:50]}...")

    print("Sorting valid nodes...")
    valid_nodes.sort(
        key=lambda x: (
            x["metrics"]["latency"] or float('inf'),
            x["metrics"]["packet_loss"]
        )
    )

    print("Grouping nodes by protocol and location...")
    vless_nodes = [node for node in valid_nodes if node["protocol"] == "vless"]
    vmess_nodes = [node for node in valid_nodes if node["protocol"] == "vmess"]
    location_groups = {}
    for node in valid_nodes:
        location = node["location"]
        if location not in location_groups:
            location_groups[location] = []
        location_groups[location].append(node)

    print("Generating configuration files...")
    create_grouped_config(valid_nodes, "all", valid_nodes_file)
    if vless_nodes:
        create_grouped_config(vless_nodes, "vless", "results/valid_vless_nodes.json")
    if vmess_nodes:
        create_grouped_config(vmess_nodes, "vmess", "results/valid_vmess_nodes.json")
    for location, nodes in location_groups.items():
        create_grouped_config(nodes, location, f"results/valid_nodes_{location}.json")
    
    print(f"Script completed successfully. Total execution time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()
