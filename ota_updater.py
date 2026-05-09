import logging
import platform
import struct
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import filedialog
import socket
import random
import threading
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
from typing import List
import time

import psutil

import wtn_config
from rmesh_parser import pack_ota_request, RmeshPacketType, pack_rmesh_packet
from wtn_node import Node


class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器，只提供选中的OTA文件"""

    def __init__(self, *args, ota_file_content=None, ota_filename=None, **kwargs):
        self.ota_file_content = ota_file_content  # 选中的文件内容
        self.ota_filename = ota_filename  # 选中的文件名
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """处理GET请求，只允许下载选中的OTA文件"""
        logging.debug(self.path)
        if self.path == f"/{self.ota_filename}" and self.ota_file_content:
            self.send_response(200)
            self.send_header("Content-type", "application/octet-stream")
            self.send_header("Content-Length", len(self.ota_file_content))
            self.end_headers()
            self.wfile.write(self.ota_file_content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File not found")


def mac_str_to_bytes(mac: str) -> bytes:
    """AA:BB:CC:DD:EE:FF  -> b'\xAA\xBB...\xFF'"""
    return bytes.fromhex(mac.replace(':', '').replace('-', ''))


class OTAUpgradeTab(tk.Frame):
    def __init__(self, parent, http_port=8000, udp_port=54321, fixed_value=bytes([0xAC, 0xBD, 0xCE, 0xDF]),
                 ifname=None):
        """
        初始化OTA升级Tab
        :param parent: 父容器（Notebook）
        :param http_port: HTTP服务器端口，默认为8000
        :param udp_port: UDP目标端口，默认为12345
        :param fixed_value: UDP包中的4字节固定值 ，默认为[0xAC, 0xBD, 0xCE, 0xDF]
        """
        super().__init__(parent)
        # RNAT MAC → IP 缓存
        self.rnat_cache: dict[str, str] = {}
        self.tree = None
        from wtn_control import Controller
        self.controller: Controller | None = None  # controller属性，初始为None，后续赋值
        self.http_port = http_port  # HTTP服务器端口
        self.udp_port = udp_port  # UDP目标端口
        self.fixed_value = fixed_value  # UDP包固定值
        self.http_server = None  # HTTP服务器实例
        self.http_thread = None  # HTTP服务器线程
        self.selected_file = None  # 用户选择的OTA文件名
        self.selected_file_content = None  # 用户选择的OTA文件的内容
        self.ifname = ifname  # 网卡名称
        self.dual_bin_files = None  # Selected dual bin files
        self.loop_running = False  # Flag to track if loop OTA is running
        self.loop_thread = None  # Thread for loop OTA

        self.auto_refresh_var = tk.IntVar(value=1)  # Variable for checkbox state
        self.auto_refresh_job = None  # To store the 'after' job ID
        self.refresh_interval_ms = 1000  # Refresh every 1 seconds

        # --- ADDED FOR OTA RETRY ---
        # 从 wtn_config 获取重试参数，如果未定义则使用默认值
        self.ota_retry_delay_s = wtn_config.OTA_RETRY_DELAY_S  # 开始重试前的等待时间（秒）
        self.ota_retry_interval_s = wtn_config.OTA_RETRY_INTERVAL_S  # 每次重试的间隔时间（秒）
        self.ota_retry_max_attempts = wtn_config.ota_retry_max_attempts  # 最大重试次数
        self.ota_process_thread = None  # 用于执行OTA和重试逻辑的线程
        # --- END ADDED ---

        # 初始化界面和HTTP服务器
        self.init_ui()
        self.start_http_server()

    def init_ui(self):
        """初始化Tkinter界面"""
        # 左侧节点列表，使用Treeview展示IP和Build Number
        self.tree = ttk.Treeview(self, columns=('No.', 'IP', 'OTA Version', 'Build', 'BSSID', 'MAC'), show='headings',
                                 selectmode='extended')
        self.tree.heading('No.', text='No.')
        self.tree.heading('IP', text='IP')
        self.tree.heading('OTA Version', text='OTA Version')
        self.tree.heading('Build', text='Build')
        self.tree.heading('BSSID', text='BSSID')
        self.tree.heading('MAC', text='MAC')
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 右侧边栏
        self.sidebar = tk.Frame(self, width=200)  # 设置最小宽度为200像素
        self.sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        self.sidebar.pack_propagate(False)  # 防止子组件改变边栏宽度

        # 在边栏中添加组件
        self.file_label = tk.Label(self.sidebar, text="OTA File: None")
        self.file_label.pack(pady=5)

        self.select_file_btn = tk.Button(self.sidebar, text="Select OTA File", command=self.select_file)
        self.select_file_btn.pack(pady=5, fill=tk.X)

        # --- ADDED BUTTONS ---
        self.select_all_btn = tk.Button(self.sidebar, text="Select All", command=self.select_all_nodes)
        self.select_all_btn.pack(pady=5, fill=tk.X)

        self.deselect_all_btn = tk.Button(self.sidebar, text="Deselect All", command=self.deselect_all_nodes)
        self.deselect_all_btn.pack(pady=5, fill=tk.X)
        # --- END ADDED BUTTONS ---

        self.ota_btn = tk.Button(self.sidebar, text="Perform OTA", command=self.perform_ota)
        self.ota_btn.pack(pady=5, fill=tk.X)

        self.loop_ota_btn = tk.Button(self.sidebar, text="Loop OTA", command=self.loop_ota)
        self.loop_ota_btn.pack(pady=5, fill=tk.X)

        self.stop_loop_ota_btn = tk.Button(self.sidebar, text="Stop Loop OTA", command=self.stop_loop_ota, state=tk.DISABLED)
        self.stop_loop_ota_btn.pack(pady=5, fill=tk.X)

        self.select_dual_bin_btn = tk.Button(self.sidebar, text="Select Dual Bin", command=self.select_dual_bin)
        self.select_dual_bin_btn.pack(pady=5, fill=tk.X)

        self.dual_bin_label = tk.Label(self.sidebar, text="Dual Bin: None", wraplength=180, justify=tk.LEFT)
        self.dual_bin_label.pack(pady=5, fill=tk.X)

        # --- ADDED FOR OTA RETRY FEEDBACK ---
        self.status_label = tk.Label(self.sidebar, text="Status: Idle", wraplength=180, justify=tk.LEFT)
        self.status_label.pack(pady=5, fill=tk.X)
        # --- END ADDED ---

        self.refresh_btn = tk.Button(self.sidebar, text="Refresh Nodes", command=self.update_nodes)
        self.refresh_btn.pack(pady=5, fill=tk.X)

        self.auto_refresh_cb = tk.Checkbutton(self.sidebar, text="Auto Refresh",
                                              variable=self.auto_refresh_var, command=self.toggle_auto_refresh)
        self.auto_refresh_cb.pack(pady=10)

        # Start auto-refresh by default
        self.schedule_next_update()

    def select_all_nodes(self):
        """Selects all items in the treeview."""
        all_items = self.tree.get_children()
        self.tree.selection_set(all_items)

    def deselect_all_nodes(self):
        """Deselects all items in the treeview."""
        self.tree.selection_set(())  # Pass an empty tuple to clear the selection

    def toggle_auto_refresh(self):
        """Starts or stops the auto-refresh scheduled job."""
        if self.auto_refresh_var.get() == 1:
            logging.info("Auto-refresh enabled.")
            self.schedule_next_update()
        else:
            logging.info("Auto-refresh disabled.")
            if self.auto_refresh_job:
                self.after_cancel(self.auto_refresh_job)
                self.auto_refresh_job = None

    def schedule_next_update(self):
        """Schedules the next execution of update_nodes."""
        self.update_nodes()
        if self.auto_refresh_var.get() == 1:
            self.auto_refresh_job = self.after(self.refresh_interval_ms, self.schedule_next_update)

    def get_local_ip(self):
        def get_windows_ip():
            preferred_ip = None
            for iface, addrs in psutil.net_if_addrs().items():
                if iface == self.ifname:
                    for addr in addrs:
                        if addr.family == socket.AF_INET and not addr.address.startswith('169.254'):
                            if addr.address.startswith('192'):
                                return addr.address
                            if preferred_ip is None:
                                preferred_ip = addr.address
            return preferred_ip

        def get_non_windows_ip():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            return socket.inet_ntoa(fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack('256s', self.ifname[:15].encode('utf-8'))
            )[20:24])

        if platform.system() == 'Windows':
            return get_windows_ip()
        else:
            # fcntl is not available on Windows, so we assume it exists on non-windows.
            import fcntl
            return get_non_windows_ip()

    def start_http_server(self):
        """启动HTTP服务器"""
        # 使用自定义处理器，传入选中的文件内容和文件名
        handler = lambda *args, **kwargs: CustomHTTPRequestHandler(
            *args, ota_file_content=self.selected_file_content, ota_filename=self.selected_file, **kwargs
        )
        self.http_server = HTTPServer(('0.0.0.0', self.http_port), handler)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever)
        self.http_thread.daemon = True
        self.http_thread.start()

    def stop_http_server(self):
        """停止HTTP服务器"""
        if self.http_server:
            # 关闭服务器套接字
            self.http_server.shutdown()
            self.http_server.server_close()
            # 等待线程结束
            if self.http_thread.is_alive():
                self.http_thread.join()
            self.http_server = None
            self.http_thread = None

    def select_file(self):
        """选择OTA文件并读取内容"""
        file_path = filedialog.askopenfilename()
        if file_path:
            try:
                # 使用二进制模式读取文件内容
                with open(file_path, 'rb') as f:
                    self.selected_file_content = f.read()
                # 仅保存文件名，而非完整路径
                self.selected_file = os.path.basename(file_path)
                self.file_label.config(text=f"OTA File: {self.selected_file}")
                # 重启HTTP服务器以更新文件内容
                self.stop_http_server()
                self.start_http_server()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read file: {str(e)}")
                logging.error("Error reading file: %s", str(e))

    def send_ota_udp(self, node_ip: str, node_mac: str, filename: str, ota_type: int):
        """
        [重构后] 发送 'OTA Request' 数据包到指定节点。
        """
        # 1. 业务层: 使用标准化工具生成负载 (Payload)
        local_ip = self.get_local_ip()
        try:
            # 协议要求 request_seq 不为0，可以递增或随机
            request_seq = random.randint(1, 255)
            payload = pack_ota_request(
                request_seq=request_seq,
                destination_mac=node_mac,
                host_server_ip=local_ip,
                host_server_port=self.http_port,
                ota_file_name=filename,
                ota_type=ota_type
            )
        except Exception as e:
            messagebox.showerror("Packing Error", f"Failed to pack OTA payload: {e}")
            logging.error(f"Failed to pack OTA payload: {e}")
            return

        # 2. 协议帧层: 使用标准化工具将负载封装成完整的R-MESH数据包
        try:
            packet = pack_rmesh_packet(
                packet_type=RmeshPacketType.OTA_REQUEST,
                payload=payload
            )
        except Exception as e:
            messagebox.showerror("Framing Error", f"Failed to frame OTA packet: {e}")
            logging.error(f"Failed to frame OTA packet: {e}")
            return

        # 发送UDP包
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(packet, (node_ip, self.udp_port))
            logging.info("Sent OTA packet to %s (%s) for file %s", node_ip, node_mac, filename)

    def loop_ota(self):
        """Loop OTA - alternate between two bin files until stopped"""
        if not self.dual_bin_files or len(self.dual_bin_files) != 2:
            messagebox.showwarning("Warning", "Please select exactly 2 bin files first")
            return

        if self.loop_running:
            messagebox.showwarning("In Progress", "Loop OTA is already running")
            return

        # Check if any nodes are selected
        selected_items = list(self.tree.selection())
        if not selected_items:
            messagebox.showwarning("Warning", "No node selected")
            return

        # Start loop OTA
        self.loop_running = True
        self.loop_ota_btn.config(state=tk.DISABLED)
        self.stop_loop_ota_btn.config(state=tk.NORMAL)
        self.select_dual_bin_btn.config(state=tk.DISABLED)

        # Start loop in separate thread
        self.loop_thread = threading.Thread(target=self._loop_ota_worker, daemon=True)
        self.loop_thread.start()

    def _loop_ota_worker(self):
        """Worker thread for loop OTA"""
        dual_bin_files = self.dual_bin_files[:]

        while self.loop_running:
            for bin_index, bin_path in enumerate(dual_bin_files):
                if not self.loop_running:
                    break

                bin_filename = os.path.basename(bin_path)
                self.after(0, self.status_label.config, {'text': f"Loop OTA: File {bin_index + 1}/2 - {bin_filename}"})

                # Read file content and set as selected file
                try:
                    with open(bin_path, 'rb') as f:
                        file_content = f.read()
                except Exception as e:
                    self.after(0, messagebox.showerror, "Error", f"Failed to read file: {str(e)}")
                    self._stop_loop_ota()
                    return

                # Set as selected file (like select_file does)
                self.selected_file = bin_filename
                self.selected_file_content = file_content
                self.after(0, self.file_label.config, {'text': f"OTA File: {bin_filename}"})

                # Get selected nodes
                selected_items = list(self.tree.selection())
                if not selected_items:
                    self.after(0, messagebox.showwarning, "Warning", "No node selected")
                    self._stop_loop_ota()
                    return

                # Build node info list for OTA (same as perform_ota)
                item_to_node = {}
                if self.controller and hasattr(self.controller, 'nodes'):
                    nodes = list(self.controller.nodes.values())
                    mac2node = {n.mac.lower(): n for n in nodes}
                    for item in selected_items:
                        node_mac = self.tree.item(item)['values'][5].lower()
                        item_to_node[item] = mac2node.get(node_mac)

                # Sort by RNAT first
                selected_items.sort(
                    key=lambda i: not (item_to_node.get(i) and getattr(item_to_node.get(i), 'rnat_flag', False)))
                ota_type = 1 if len(selected_items) == len(self.tree.get_children()) else 2

                # Send OTA to nodes that need upgrade
                target_nodes_info = []
                for item in selected_items:
                    _, node_ip, current_ota_version, _, bssid, node_mac = self.tree.item(item)['values']

                    if current_ota_version == bin_filename:
                        logging.info(f"Skipping node {node_mac} as it already has the target version: {bin_filename}")
                        continue

                    resolved_ip = self.rnat_cache.get(bssid.lower(), node_ip)
                    self.send_ota_udp(resolved_ip, node_mac, bin_filename, ota_type)
                    target_nodes_info.append({'mac': node_mac, 'ip': resolved_ip})

                if not target_nodes_info:
                    self.after(0, messagebox.showinfo, "Already Updated", "All selected nodes already have the target OTA version.")
                    continue

                # Wait for all nodes to complete OTA using the same retry logic as perform_ota
                self._wait_for_ota_loop(target_nodes_info, bin_filename)

                if not self.loop_running:
                    break

            # Delay between loops
            if self.loop_running:
                self.after(0, self.status_label.config, {'text': "Waiting 30s before next file..."})
                time.sleep(30)

        self._stop_loop_ota()

    def _wait_for_ota_loop(self, target_nodes_info, filename):
        """Wait for all nodes to complete OTA in loop mode (synchronous)"""
        nodes_to_wait = list(target_nodes_info)

        # Initial delay before checking
        time.sleep(self.ota_retry_delay_s)

        for attempt in range(self.ota_retry_max_attempts):
            if not self.loop_running:
                return

            if not nodes_to_wait:
                self.after(0, self.status_label.config, {'text': f"All nodes OTA completed: {filename}"})
                return

            # Check node status
            mac_to_node_map = {}
            if self.controller and hasattr(self.controller, 'nodes'):
                mac_to_node_map = {
                    node.mac.lower(): node for node in self.controller.nodes.values()
                }

            still_pending = []
            for node_info in nodes_to_wait:
                node_obj = mac_to_node_map.get(node_info['mac'].lower())
                ota_version = getattr(node_obj, 'ota_version', '') if node_obj else ''

                # Must wait until OTA version equals filename (without * prefix)
                is_ota_finished = (ota_version == filename)

                if not is_ota_finished:
                    still_pending.append(node_info)

            nodes_to_wait = still_pending

            if not nodes_to_wait:
                self.after(0, self.status_label.config, {'text': f"All nodes OTA completed: {filename}"})
                return

            # Retry for pending nodes
            self.after(0, self.status_label.config, {'text': f"Waiting for {len(nodes_to_wait)} node(s) - {filename}"})

            for node_info in nodes_to_wait:
                self.send_ota_udp(node_info['ip'], node_info['mac'], filename, 2)

            if attempt < self.ota_retry_max_attempts - 1:
                time.sleep(self.ota_retry_interval_s)

        # Timeout
        self.after(0, self.status_label.config, {'text': f"Timeout: {len(nodes_to_wait)} node(s) failed"})

    def stop_loop_ota(self):
        """Stop loop OTA"""
        self.loop_running = False
        self._stop_loop_ota()

    def _stop_loop_ota(self):
        """Internal method to stop loop OTA and reset UI"""
        self.loop_running = False
        self.after(0, self.loop_ota_btn.config, {'state': tk.NORMAL})
        self.after(0, self.stop_loop_ota_btn.config, {'state': tk.DISABLED})
        self.after(0, self.select_dual_bin_btn.config, {'state': tk.NORMAL})
        self.after(0, self.status_label.config, {'text': "Status: Idle"})

    def select_dual_bin(self):
        """Select two bin files for dual bin OTA"""
        file_paths = filedialog.askopenfilename(multiple=True)
        if file_paths:
            file_list = list(file_paths)
            if len(file_list) != 2:
                messagebox.showwarning("Warning", "Please select exactly 2 bin files")
                return
            self.dual_bin_files = file_list
            display_text = "Dual Bin:\n" + "\n".join([os.path.basename(f) for f in file_list])
            self.dual_bin_label.config(text=display_text)

    def perform_ota(self):
        """执行OTA升级，优先发RNAT节点，并带重试机制"""
        if self.ota_process_thread and self.ota_process_thread.is_alive():
            messagebox.showwarning("In Progress", "An OTA process is already running.")
            return

        selected_items = list(self.tree.selection())
        if not selected_items:
            messagebox.showwarning("Warning", "No node selected")
            return
        if not self.selected_file:
            messagebox.showwarning("Warning", "No OTA file selected")
            return

        # 禁用按钮并更新状态
        self.ota_btn.config(state=tk.DISABLED)
        self.status_label.config(text="Starting OTA...")

        # 1. 构建id到Node的映射
        item_to_node = {}
        if self.controller and hasattr(self.controller, 'nodes'):
            nodes: List[Node] = list(self.controller.nodes.values())
            mac2node = {n.mac.lower(): n for n in nodes}  # 用mac查Node对象
            for item in selected_items:
                node_mac = self.tree.item(item)['values'][5].lower()  # 修正: 使用索引5获取MAC
                item_to_node[item] = mac2node.get(node_mac)

        # 2. 给selected_items排序，rnat_flag=True的排前面
        selected_items.sort(
            key=lambda i: not (item_to_node.get(i) and getattr(item_to_node.get(i), 'rnat_flag', False)))
        ota_type = 1 if len(selected_items) == len(self.tree.get_children()) else 2

        target_nodes_info = []
        for item in selected_items:
            # 从Treeview中获取节点的显示信息
            _, node_ip, current_ota_version, _, bssid, node_mac = self.tree.item(item)['values']

            # 检查当前节点的OTA版本是否已经与目标文件名相同
            if current_ota_version == self.selected_file:
                logging.info(f"Skipping node {node_mac} as it already has the target version: {self.selected_file}")
                continue  # 如果版本相同，则跳过此节点，不发送OTA指令

            resolved_ip = self.rnat_cache.get(bssid.lower(), node_ip)
            # 初始发送
            self.send_ota_udp(resolved_ip, node_mac, self.selected_file, ota_type)
            # 只有需要升级的节点才被加入重试列表
            target_nodes_info.append({'mac': node_mac, 'ip': resolved_ip})

        # 检查在过滤后是否还有需要升级的节点
        if not target_nodes_info:
            messagebox.showinfo("Already Updated", "All selected nodes already have the target OTA version.")
            self.finalize_ota_process()  # 重置UI状态
            return  # 退出函数，不启动重试线程

        # 在新线程中启动重试逻辑以避免UI阻塞
        self.ota_process_thread = threading.Thread(
            target=self._ota_retry_worker,
            args=(target_nodes_info, self.selected_file, ota_type),
            daemon=True
        )
        self.ota_process_thread.start()

    def _ota_retry_worker(self, target_nodes_info: List[dict], filename: str, ota_type: int):
        """在后台线程中处理OTA重试逻辑。"""
        # 1. 初始延迟，等待节点响应
        time.sleep(self.ota_retry_delay_s)

        nodes_to_retry = list(target_nodes_info)

        # 2. 重试循环
        for attempt in range(self.ota_retry_max_attempts):
            if not nodes_to_retry:  # 如果已经没有需要重试的节点，提前退出
                break

            # 在UI线程上更新状态
            status_text = f"Checking status (Attempt {attempt + 1}/{self.ota_retry_max_attempts})"
            self.after(0, self.status_label.config, {'text': status_text})

            # 在每次重试时，重新构建 MAC -> Node 对象的查找字典，以获取最新状态。
            # 因为 self.controller.nodes 的键不是 MAC，所以我们必须遍历其值。
            mac_to_node_map = {}
            if self.controller and hasattr(self.controller, 'nodes'):
                # self.controller.nodes.values() 包含了所有最新的 Node 对象
                mac_to_node_map = {
                    node.mac.lower(): node for node in self.controller.nodes.values()
                }

            still_pending_nodes = []
            for node_info in nodes_to_retry:
                # 使用新建的查找字典，通过小写MAC地址安全地获取最新的节点对象
                node_obj = mac_to_node_map.get(node_info['mac'].lower())

                # 安全地获取ota_version。如果节点下线(node_obj为None)，ota_version会是''
                ota_version = getattr(node_obj, 'ota_version', '') if node_obj else ''

                # 完善的成功条件判断
                # 条件1: OTA正在进行中 (以'*'开头)
                is_ota_started = ota_version.startswith('*')
                # 条件2: OTA已成功完成 (版本号与文件名一致)
                is_ota_finished = (ota_version == filename)

                # 如果两个成功条件都不满足，则认为该节点需要重试
                if not (is_ota_started or is_ota_finished):
                    still_pending_nodes.append(node_info)
                else:
                    logging.info(
                        f"Node {node_info['mac']} confirmed OTA status: {ota_version}. Removing from retry list.")

            nodes_to_retry = still_pending_nodes

            # 3. 判断是否需要继续重试
            if not nodes_to_retry:
                # 所有节点都已开始或完成OTA
                success_msg = "Success: All nodes started or finished OTA."
                self.after(0, self.status_label.config, {'text': success_msg})
                self.after(0, messagebox.showinfo, "Success",
                           "All selected nodes have started or finished the OTA process.")
                break  # 成功，退出重试循环

            # 仍有节点未开始，执行重试
            retry_macs = [n['mac'] for n in nodes_to_retry]
            retry_msg = f"Retrying ({attempt + 1}/{self.ota_retry_max_attempts}) for {len(nodes_to_retry)} node(s)..."
            self.after(0, self.status_label.config, {'text': retry_msg})
            logging.info(f"OTA Retry {attempt + 1}: Resending packets to nodes: {', '.join(retry_macs)}")

            for node_info in nodes_to_retry:
                self.send_ota_udp(node_info['ip'], node_info['mac'], filename, ota_type)

            # 如果不是最后一次尝试，则等待指定间隔
            if attempt < self.ota_retry_max_attempts - 1:
                time.sleep(self.ota_retry_interval_s)

        else:  # for-else循环：仅当循环正常结束（未被break）时执行
            if nodes_to_retry:
                failed_macs = [node['mac'] for node in nodes_to_retry]
                error_msg = f"OTA failed for the following nodes:\n" + "\n".join(failed_macs)
                status_err_msg = f"Error: {len(failed_macs)} node(s) failed to start."
                self.after(0, self.status_label.config, {'text': status_err_msg})
                self.after(0, messagebox.showerror, "OTA Failed", error_msg)
                logging.error(f"OTA process finished with failures: {', '.join(failed_macs)}")

        # 4. 最终处理：无论成功与否，都重新启用按钮并重置状态
        self.after(0, self.finalize_ota_process)

    def finalize_ota_process(self):
        """在UI线程上重新启用OTA按钮并重置状态文本。"""
        self.ota_btn.config(state=tk.NORMAL)
        self.status_label.config(text="Status: Idle")

    def update_nodes(self):
        """从controller更新节点列表"""
        if self.controller and hasattr(self.controller, 'nodes'):
            # Preserve selection
            selected_macs = {self.tree.item(item)['values'][5] for item in self.tree.selection()}  # 修正: 使用索引5获取MAC

            nodes: List[Node] = list(
                filter(lambda item: item.ip != "0.0.0.0" and item.mac not in wtn_config.ap_mac_list,
                       self.controller.nodes.values()))
            # 清空当前列表
            for i in self.tree.get_children():
                self.tree.delete(i)
            # 填充新节点信息
            new_selection = []
            for i, node in enumerate(nodes, 1):
                item_id = self.tree.insert('', 'end',
                                           values=(i, node.ip, node.ota_version, node.build, node.bssid, node.mac))
                if node.mac in selected_macs:
                    new_selection.append(item_id)

            # Restore selection
            if new_selection:
                self.tree.selection_set(new_selection)

            # 重建 RNAT 缓存
            self.rnat_cache.clear()
            # 先找出所有标记为 RNAT 的节点（示例用 rnat_config.rnat_mac_list）
            for n in nodes:
                if getattr(n, 'rnat_flag', False):  # Safely check for rnat_flag
                    # 把 RNAT 自身的 MAC → IP 放进去
                    self.rnat_cache[n.mac.lower()] = n.ip

    def set_controller(self, controller):
        """设置controller属性并刷新节点数据"""
        self.controller = controller
        self.update_nodes()

    def __enter__(self):
        """进入Tab时刷新节点数据"""
        self.update_nodes()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """离开Tab时可执行清理操作"""
        # Stop auto-refresh when switching tabs to save resources
        if self.auto_refresh_job:
            self.after_cancel(self.auto_refresh_job)
            self.auto_refresh_job = None
            self.auto_refresh_var.set(0)  # Uncheck the box
            logging.info("Auto-refresh stopped due to tab exit.")
        pass

    def __del__(self):
        """清理资源"""
        self.stop_http_server()
