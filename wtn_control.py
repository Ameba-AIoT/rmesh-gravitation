import logging
import os
import tkinter as tk
import tkinter.messagebox as messagebox
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import List, Set

from color_group import ColorConfigManager
from packet_model import PacketModel
from color_config import node_highlight_color
from utils import update_config_key
from wtn_config import *
import re

from wtn_dut import AmebaDevice
import time
import threading
import serial.tools.list_ports
import wtn_config
import traceback
import random

from wtn_log_utils import save_file, delete_old_files
from wtn_node import Node
from wtn_server import WTNServer
from wtn_ui import Win
from wtn_wall import Wall


AP_COLOR = "#228B22"

ping_results: {str: str} = {}


class Controller:
    ui: object
    def __init__(self, chosen_iface:str):
        self.color_manager = None
        self.chosen_iface = chosen_iface
        self.scan_list_refresh_counter = None
        self.binding_nodes = None
        self.start_point = None
        self.layout_lock = None
        self.auto_move_nodes = None
        self.table_window_id = None
        self.auto_layout = None
        self.node_activities_log_file = None
        self.selected_wall = None
        self.highlight_node_mac = None
        self.in_add_wall = None
        self.walls = None
        self.need_send_rssi_table = None
        self.log_node = None
        self.selected_node = None
        # For multi-select
        self.selected_nodes: Set[Node] = set()
        self.thread_status = None
        self.aps = None
        self.nodes: {int: Node} = {}
        self.uart_devices: {str: AmebaDevice} = {}
        self.info_embedded = None
        self.table_frame = None
        self.node_info_table_frame = None
        self.node_info_table_window_id = None

    def init(self, ui):
        self.ui: Win = ui
        # node id to node object, node id is from TK GUI framework
        self.nodes: {int: Node} = {}
        self.aps = set()
        self.thread_status = True
        self.ui.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.selected_node:str | None = None
        self.log_node = None
        self.need_send_rssi_table = True
        self.walls = {}
        self.in_add_wall = False
        self.selected_wall = None
        self.start_point = None
        self.auto_move_nodes = {}
        self.layout_lock = threading.Lock()
        self.table_window_id = None
        self.table_frame = None
        self.auto_layout = True
        self.info_embedded = True
        self.highlight_node_mac = ""
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        self.node_activities_log_file = os.path.join(log_dir,
                                                     f"NodeActivities_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.txt")
        self.scan_list_refresh_counter = 0
        threading.Thread(target=self.read_device_output_thread).start()
        threading.Thread(target=self.refresh_relation_thread).start()
        self.ui_batch_update()
        threading.Thread(target=self.serial_port_scan_thread).start()
        offset_range = 10
        ap_index = 0
        for mac in wtn_config.ap_mac_list:
            if ap_index == 0:
                self.add_ap(self.ui.grid_width // self.ui.cell_width / 2, self.ui.grid_height//self.ui.cell_height / 2, mac)
            elif ap_index == 1:
                self.add_ap(ui.cols - wtn_config.ap_x, wtn_config.ap_y, mac)
            else:
                offset_x = random.uniform(-offset_range, offset_range)
                offset_y = random.uniform(-offset_range, offset_range)
                self.add_ap(wtn_config.ap_x + offset_x, wtn_config.ap_y + offset_y, mac)
            ap_index = ap_index + 1

        if wtn_config.clear_log_files:
            delete_old_files(os.path.join(os.getcwd(), "logs"), wtn_config.log_file_expire_threshold_in_ten_minutes)
        # com:lifespan
        self.binding_nodes = {}

        config_file = Path("color_config.json")
        # 加载配置并创建管理器
        if config_file.exists():
            self.color_manager = ColorConfigManager.load_from_file(config_file)
        else:
            self.color_manager = ColorConfigManager([])

        server = WTNServer(report_timeout=wtn_config.REMOTE_NODE_TIMEOUT, ifname=self.chosen_iface)
        server.set_node_connected_callback(self.on_node_connected)
        server.set_node_disconnected_callback(self.on_node_disconnected)
        server.set_node_report_callback(self.on_node_report)

        try:
            print("Starting WTN server...")
            server.start(wtn_config.REMOTE_CONNECTION_PROTOCOL)
        except KeyboardInterrupt:
            print("WTN server interrupted.")
        finally:
            print("Stopping WTN server...")
            # server.stop()
            print("WTN server stopped.")

    def on_highlight_node_mac_changed(self, mac):
        self.highlight_node_mac=mac

    def on_node_connected(self, addr, rnat_flag):
        logging.info(f"Node connected: {addr}")
        self.add_remote_node(addr, rnat_flag)
        current_time = datetime.now().strftime("%H:%M:%S:%f")[:-3]
        if self.node_activities_log_file:
            with open(self.node_activities_log_file, 'a') as file:
                file.write(f"{addr}: online\t{current_time}\n")

    def on_node_disconnected(self, mac):
        current_time = datetime.now().strftime("%H:%M:%S:%f")[:-3]
        if self.node_activities_log_file:
            with open(self.node_activities_log_file, 'a') as file:
                file.write(f"{mac}: offline\t{current_time}\n")
        node = self.find_node_by_mac(mac)
        if node:
            node.disconnect()
            self.clear_connect_lines_and_marks_for(node)
            self.redraw_connection_to_father()
            self.redraw_connection_to_2nd_target()

        logging.info(f"Node disconnected: {mac}")

    def on_node_report(self, report, packet: PacketModel):
        def resolve_out_put(text, children_update, data_update):
            regex_rules = {
                "mac": r"wtn_self_mac:([\b\w:]+)",
                "bssid": r"wtn_bssid:([\b\w:]+)",
                "father_mac": r"wtn_father:([\b\w:/]+)",
                "ip": r"Interface \d IP address : ([\d\.,]+)",
                "score": r"wtn_score:([\d\.\w, -]+)",
                "aid": r"wtn_aid:(\d+)",
                "debug_text": r"debug:(.*)$"
            }
            # child-3:%x/%x/%x
            if children_update:
                match = re.search(r"(child-\d+:[\w/]*)", text)
                if match:
                    children_update(match.group(1).strip())
            if data_update:
                for name, regex in regex_rules.items():
                    match = re.search(regex, text)
                    if match:
                        data_update(name, match.group(1).strip())

        def update_node_data(name, value, node):
            # logging.debug(f"update UI for {name}: {value}")
            if name == "father_mac" and value != node.father_mac:
                logging.info(f"node {node.mac.split(":")[-1]} 's father changed from {node.father_mac.split(":")[-1]} to {value.split(":")[-1]}")
                node.should_relocate = True
                related_nodes: List[Node] = list(filter(lambda n: n.father_mac in [value, node.father_mac], self.nodes.values()))
                for related_node in related_nodes:
                    related_node.should_relocate = True

            setattr(node, name, value), node.refreshUI(embedded=self.info_embedded)
            self.ping_text_layout_auto_adjust(node)

        
        def node_switch_record(node_activities_log_file, packet: PacketModel, mac, node):
            current_time = datetime.now().strftime("%H:%M:%S:%f")[:-3]
            if packet.father_mac != node.father_mac:
                new_father = packet.father_mac
                new_candidate = packet.candidate_mac
                new_father_score = packet.father_score
                new_candidate_score = packet.candidate_score

                old_father = node.father_mac
                old_candidate = node.candidate_mac
                old_father_score = None
                old_candidate_score = None
                if node.score:
                    mac_to_score = {part[:2]: part[2:] for part in node.score.split(', ')}
                    old_father_score = mac_to_score[old_father.split(":")[-1]]
                    old_candidate_score = mac_to_score[old_candidate.split(":")[-1]]

                if node_activities_log_file:
                    with open(node_activities_log_file, 'a') as file:
                        file.write(f"{mac}: switch\t{current_time}\t"
                                f"{old_father.split(":")[-1]}/{old_candidate.split(":")[-1]}[{old_father_score}/{old_candidate_score}]"
                                f" to {new_father.split(":")[-1]}/{new_candidate.split(":")[-1]}[{new_father_score}/{new_candidate_score}]\n")

        mac = report.get("mac")
        node = self.find_node_by_mac(mac)
        try:
            node_switch_record(self.node_activities_log_file, packet, mac, node)
        except Exception as e:
            logging.error(f"node {mac} switch log error: {e}")

        if not node:
            logging.error(f"update info for non-existing node {mac}")
            return
        node.online = True
        node.last_report_timestamp = datetime.now()
        node.build = packet.build
        node.ota_version = packet.ota_version
        original_rnat_flag = node.rnat_flag
        node.rnat_flag = packet.rnat_flag
        if original_rnat_flag != node.rnat_flag:
            logging.warning(f"Node {mac} rnat_flag changed from {original_rnat_flag} to {node.rnat_flag}")
        node.scan_list = packet.scan_list
        node.candidate_mac = packet.candidate_mac
        for record in report.get('payload') or []:
            resolve_out_put(record.get('data'), node.update_children_info, lambda name, value: update_node_data(name, value, node))
        logging.info(f"Node report: {packet}")

    def find_node_by_mac(self, mac)->Node:
        nodes = list(filter(lambda item: item.mac == mac, self.nodes.values()))
        if not nodes:
            logging.info(f"Node {mac} not found")
        elif len(nodes) != 1:
            logging.error(f"wrong node count: {len(nodes)} - {nodes}")
        return nodes[0] if nodes else None

    def relocate_remote_nodes(self):
        if not self.layout_lock.acquire(blocking=False):
            logging.info("Could not acquire lock, skipping execution of relocate_remote_nodes")
            return

        try:
            horizontal_link_length = wtn_config.HORIZONTAL_LINK_LENGTH or 10
            vertical_link_length = wtn_config.VERTICAL_LINK_LENGTH or 10

            grid_width = self.ui.grid_width // self.ui.cell_width
            grid_height = self.ui.grid_height // self.ui.cell_height

            # Filter AP nodes
            aps = list(filter(lambda item: item in self.aps, self.nodes.values()))
            occupied_positions = set()

            # Default layout mode: "horizontal" or "vertical"
            layout_mode = getattr(wtn_config, "LAYOUT_MODE", "horizontal")

            for ap in aps:
                x, y = ap.x, ap.y
                occupied_positions.add((x, y))
                # Recursively assign positions for the subtree of the AP node
                self._assign_positions(
                    node=ap,
                    x=x,
                    y=y,
                    mode=layout_mode,
                    hl=horizontal_link_length,
                    vl=vertical_link_length,
                    occupied_positions=occupied_positions,
                    grid_width=grid_width,
                    grid_height=grid_height,
                    level=0,
                    parent_direction=None
                )
        finally:
            self.layout_lock.release()

    def _assign_positions(self, node, x, y, mode, hl, vl, occupied_positions, grid_width, grid_height, level,
                          parent_direction):
        """
        Recursively assign positions to the child nodes of a given node:
          - For the first level (parent_direction is None), the child nodes are evenly divided into two groups (left/right or up/down).
          - For subsequent levels, all child nodes extend in the same direction as specified by parent_direction.
        """
        # Get and sort direct child nodes
        children = [n for n in self.nodes.values() if n.father_node == node]
        children = sorted(children, key=lambda n: n.mac)

        # If the current node's position has changed, mark children for relocation
        if x != node.x or y != node.y:
            for child in children:
                child.should_relocate = True

        if not children:
            return

        # First level: divide children into two groups evenly
        if parent_direction is None:
            mid = len(children) // 2
            group1 = children[:mid]
            group2 = children[mid:]
            if mode == "horizontal":
                # Group1 to the left, group2 to the right
                self._layout_group(base_x=x, base_y=y, nodes_group=group1, mode=mode, direction=-1,
                                   hl=hl, vl=vl, occupied_positions=occupied_positions,
                                   grid_width=grid_width, grid_height=grid_height, level=level + 1)
                self._layout_group(base_x=x, base_y=y, nodes_group=group2, mode=mode, direction=1,
                                   hl=hl, vl=vl, occupied_positions=occupied_positions,
                                   grid_width=grid_width, grid_height=grid_height, level=level + 1)
            else:  # mode == "vertical"
                # Group1 to the top, group2 to the bottom
                self._layout_group(base_x=x, base_y=y, nodes_group=group1, mode=mode, direction=-1,
                                   hl=hl, vl=vl, occupied_positions=occupied_positions,
                                   grid_width=grid_width, grid_height=grid_height, level=level + 1)
                self._layout_group(base_x=x, base_y=y, nodes_group=group2, mode=mode, direction=1,
                                   hl=hl, vl=vl, occupied_positions=occupied_positions,
                                   grid_width=grid_width, grid_height=grid_height, level=level + 1)
        else:
            # Subsequent levels: assign all children in the parent's extension direction
            self._layout_group(base_x=x, base_y=y, nodes_group=children, mode=mode, direction=parent_direction,
                               hl=hl, vl=vl, occupied_positions=occupied_positions,
                               grid_width=grid_width, grid_height=grid_height, level=level + 1)

    def _layout_group(self, base_x, base_y, nodes_group, mode, direction, hl, vl, occupied_positions, grid_width,
                      grid_height, level):
        """
        Assign positions to a group of child nodes:
          - For horizontal layout, all nodes are placed one cell to the left or right of the parent, with vertical offsets evenly distributed.
          - For vertical layout, all nodes are placed one cell above or below the parent, with horizontal offsets evenly distributed.
        """
        count = len(nodes_group)
        for i, child in enumerate(nodes_group):
            # If layout on demand is enabled and the child does not require relocation,
            # check if the child's current position is already occupied.
            if getattr(wtn_config, "layout_on_demand", False) and not child.should_relocate:
                if (child.x, child.y) in occupied_positions:
                    # The current position is already occupied; mark for relocation.
                    child.should_relocate = True
                else:
                    occupied_positions.add((child.x, child.y))
                    self._assign_positions(child, child.x, child.y, mode, hl, vl,
                                           occupied_positions, grid_width, grid_height,
                                           level + 1, direction)
                    continue

            if mode == "horizontal":
                candidate_x = base_x + direction * hl
                # Calculate vertical offset to distribute nodes evenly
                offset = int(round((i - (count - 1) / 2) * vl))
                candidate_y = base_y + offset
            else:  # mode == "vertical"
                candidate_y = base_y + direction * vl
                # Calculate horizontal offset to distribute nodes evenly
                offset = int(round((i - (count - 1) / 2) * hl))
                candidate_x = base_x + offset

            # Adjust candidate position to avoid overlap with already occupied positions
            candidate = self._adjust_position(candidate_x, candidate_y, mode, hl, vl, occupied_positions, grid_width,
                                              grid_height)
            if candidate is None:
                logging.warning(f"Unable to assign a valid position for node {child.mac}")
                continue
            candidate_x, candidate_y = candidate

            occupied_positions.add((candidate_x, candidate_y))
            logging.debug(f"Node: {child.mac.split(':')[-1]} set to x:{candidate_x} y:{candidate_y}")
            event = type('Event', (object,), {'x': candidate_x, 'y': candidate_y})()
            self.drag_node(event, child)
            child.should_relocate = False

            # Recursively assign positions for the child node's subtree, passing the current extension direction
            self._assign_positions(child, candidate_x, candidate_y, mode, hl, vl,
                                   occupied_positions, grid_width, grid_height,
                                   level, direction)

    def _adjust_position(self, x, y, mode, hl, vl, occupied_positions, grid_width, grid_height, max_attempts=10):
        """
        Check if (x, y) is already occupied; if so, adjust the position slightly.
        For horizontal mode, adjust vertically; for vertical mode, adjust horizontally.
        Returns None if a valid position cannot be found after max_attempts.
        """
        attempts = 0
        orig_x, orig_y = x, y
        while (x, y) in occupied_positions:
            attempts += 1
            if attempts > max_attempts:
                return None
            if mode == "horizontal":
                # In horizontal mode, keep x fixed and adjust y
                y += vl
                if y >= grid_height:
                    y = orig_y - vl  # try the opposite side
            else:
                # In vertical mode, keep y fixed and adjust x
                x += hl
                if x >= grid_width:
                    x = orig_x - hl
        if 0 <= x < grid_width and 0 <= y < grid_height:
            return (x, y)
        logging.error(f"Unable to assign a valid position for node {x}, {y}")
        return None

    def serial_port_scan_thread(self):
        time.sleep(2)
        while self.thread_status:
            if wtn_config.Node_Mode == ConnectionType.SOCKET:
                time.sleep(5)
                continue
            try:
                logging.debug(f"Scan for serial port changes.")

                ports = serial.tools.list_ports.comports()
                scanned_ports = [port.device for port in ports]
                logging.info(f"Scanned serial ports: {", ".join(scanned_ports)}" if scanned_ports else "No available serial port.")

                added_coms = self.uart_devices.keys()
                for com in added_coms:
                    if self.uart_devices[com] and self.uart_devices[com].node and (self.uart_devices[com].node.ip == default_ip or self.uart_devices[com].node.ip is None):
                        self.uart_devices[com].node.ip = self.uart_devices[com].get_ip()
                    if com in scanned_ports:
                        scanned_ports.remove(com)
                        if self.uart_devices[com].node is None: # bind node and COM
                            logging.info(f"{com} does not have a bound node")
                            com_mac = self.uart_devices[com].get_mac()
                            logging.info(f"{com} have MAC addr {com_mac}")
                            existed_node = self.find_node_by_mac(com_mac)
                            logging.info(f"{com_mac} have existed_node={existed_node}")
                            if existed_node is not None:
                                self.uart_devices[com].node = existed_node
                                existed_node.device = self.uart_devices[com]
                                existed_node.com = com
                                logging.info(f"{com} is bound with {existed_node}")

                    else: # unbind inactive COM with its node, but not delete node
                        self.uart_devices[com].node.device = None
                        self.uart_devices.pop(com)
                        logging.info(f"{com_mac} is inactive")

                # handle newly discovered COMs
                for com in scanned_ports:
                    new_dev = AmebaDevice(com)
                    self.uart_devices[com] = new_dev
                    logging.info(f"find new UART {com}")
                    new_dev_mac = new_dev.get_mac()
                    logging.info(f"{com} have MAC addr {new_dev_mac}")
                    if new_dev_mac == default_mac:
                        continue
                    related_node = self.find_node_by_mac(new_dev_mac)
                    logging.info(f"{new_dev_mac} have existed_node={related_node}")
                    if related_node is None:
                        self.add_remote_node(new_dev_mac, 0, com)
                        related_node = self.find_node_by_mac(new_dev_mac)
                        logging.info(f"{com} with MAC addr {new_dev_mac} creates a new node {related_node}")
                    new_dev.node = related_node
                    related_node.device = new_dev
                    related_node.com = com
                    logging.info(f"{com} is bound with {related_node}")

            except Exception as e:
                print(e)
            time.sleep(1)

    def ui_batch_update(self):
        try:
            if wtn_config.Node_Mode == ConnectionType.SOCKET and self.auto_layout:
                self.relocate_remote_nodes()
            if ping_results:
                for node_id, value in ping_results.items():
                    node = self.nodes[node_id]
                    if (node == None):
                        continue
                    ping_text = node.ping_text
                    if node.ping_monitor and not node.ping_monitor.stop_event.is_set():
                        self.ui.tk_canvas_node_grid.itemconfig(ping_text, text=value if self.info_embedded else "")
                    if wtn_config.Node_Mode == ConnectionType.UART:
                        self.ui.tk_canvas_node_grid.itemconfig(node.node_text, text=f"{node.get_basic_info_text()}\n{node.ip}{node.get_suffix()}" if self.info_embedded else "")
                    else:
                        self.ui.tk_canvas_node_grid.itemconfig(node.node_text,
                                                               text=f"{node.get_basic_info_text()}{node.get_suffix()}" if self.info_embedded else "")
            self.scan_list_refresh_counter += 1
            if self. scan_list_refresh_counter < SCAN_LIST_REFRESH_PERIOD:
                return
            self.scan_list_refresh_counter = 0
            # update popup window
            if self.selected_node in self.nodes:
                selected_node = self.nodes[self.selected_node]

                coordinate = self.ui.tk_canvas_node_grid.coords(self.selected_node)
                x, y = coordinate[0], coordinate[1]
                if not self.info_embedded:
                    self.create_or_update_node_info_table(self.ui.tk_canvas_node_grid, x, y, selected_node,
                                                            x_offset=20, y_offset=-20)
                self.table_window_id = self.create_table(self.ui.tk_canvas_node_grid, x, y, selected_node.scan_list,
                                                         x_offset=20, y_offset=20)
        except Exception as e:
            print(e)
        finally:
            # Recursively push the task into main eventloop
            self.ui.tk_canvas_node_grid.after(int(wtn_config.ui_redraw_interval), self.ui_batch_update)

    def on_closing(self):
        self.thread_status = False
        self.ui.destroy()
        os._exit(0)

    def create_table(self, canvas, x, y, data, x_offset=20, y_offset=20):
        if self.table_frame:
            self.table_frame.destroy()
        self.table_frame = tk.Frame(canvas)
        for i, item in enumerate(data):
            mac_label = tk.Label(self.table_frame, text=item["mac_last_byte"], borderwidth=1, relief="solid")
            mac_label.grid(row=i, column=0, sticky="nsew")
            score_label = tk.Label(self.table_frame, text=item["score"], borderwidth=1, relief="solid")
            score_label.grid(row=i, column=1, sticky="nsew")
            help_num_label = tk.Label(self.table_frame, text=item["can_help_num"], borderwidth=1, relief="solid")
            help_num_label.grid(row=i, column=2, sticky="nsew")
        return canvas.create_window(x + x_offset, y + y_offset, window=self.table_frame, anchor="nw")

    def create_or_update_node_info_table(self, canvas, x, y, node, x_offset=20, y_offset=20):
        if not self.node_info_table_frame:
            # 创建表格框架
            self.node_info_table_frame = tk.Frame(canvas)
            self._populate_table(node)
            self.node_info_table_window_id = canvas.create_window(
                x + x_offset, y + y_offset, window=self.node_info_table_frame, anchor="nw"
            )
            # 动态获取高度
            self.node_info_table_frame.update_idletasks()
            table_height = self.node_info_table_frame.winfo_height()
            canvas.move(self.node_info_table_window_id, 0, -table_height)
        else:
            try:
                self.node_info_table_frame.grid_slaves(row=0, column=1)[0].config(text=node.ip)
                self.node_info_table_frame.grid_slaves(row=1, column=1)[0].config(text=node.mac)
                self.node_info_table_frame.grid_slaves(row=2, column=1)[0].config(text=node.score)
            except IndexError:
                pass

            self.node_info_table_frame.update_idletasks()
            table_height = self.node_info_table_frame.winfo_height()
            canvas.coords(self.node_info_table_window_id, x + x_offset, y + y_offset - table_height)

    def _populate_table(self, node):
        # 添加标签标题
        tk.Label(self.node_info_table_frame, text="IP", borderwidth=1, relief="solid",
                 font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky="nsew")
        tk.Label(self.node_info_table_frame, text="MAC", borderwidth=1, relief="solid",
                 font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky="nsew")
        tk.Label(self.node_info_table_frame, text="Score", borderwidth=1, relief="solid",
                 font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky="nsew")

        # 添加数据
        tk.Label(self.node_info_table_frame, text=node.ip, borderwidth=1, relief="solid").grid(row=0, column=1,
                                                                                               sticky="nsew")
        tk.Label(self.node_info_table_frame, text=node.mac, borderwidth=1, relief="solid").grid(row=1, column=1,
                                                                                                    sticky="nsew")
        tk.Label(self.node_info_table_frame, text=node.score, borderwidth=1, relief="solid").grid(row=2, column=1,
                                                                                                    sticky="nsew")

    def select_node(self, evt):
        shift_key_mask_code = 0x0001
        shift_pressed = evt.state & shift_key_mask_code == 0x0001
        logging.debug(f"shift_pressed: {shift_pressed}")

        if self.in_add_wall:
            self.select_wall(evt)
            return

        if self.selected_node and self.selected_node not in self.nodes.keys():
            if self.ui.tk_canvas_node_grid.type(self.selected_node) not in ['text', 'line', 'window']:
                try:
                    self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="#e0e0e0")  # Reset color of previously selected node
                except Exception as e:
                    print(e)
                    logging.error(self.selected_node)
                    logging.error(self.ui.tk_canvas_node_grid.type(self.selected_node))
                    logging.error(e)
                    traceback.print_exc()

        if self.selected_node and self.selected_node in self.nodes.keys():
            self.update_node_color(self.selected_node, 1)
        select_node = self.ui.tk_canvas_node_grid.find_closest(evt.x, evt.y)[0]

        if self.selected_wall and self.selected_wall in self.walls:
            self.ui.tk_canvas_node_grid.itemconfig(self.selected_wall, fill="dark grey")

        if select_node in self.walls.keys():
            self.selected_wall = select_node
            self.ui.tk_canvas_node_grid.itemconfig(self.selected_wall, fill="yellow")
            return

        self.selected_node = select_node
        if self.ui.tk_canvas_node_grid.type(self.selected_node) == 'text':
            for node_id, the_node in self.nodes.items():
                if the_node.node_text == self.selected_node:
                    self.selected_node = node_id
                    break

        self.log_node = self.selected_node

        if self.selected_node and self.selected_node not in self.nodes.keys():
            if self.ui.tk_canvas_node_grid.type(self.selected_node) not in ['text', 'line', 'window']:
                self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="yellow")  # Change color of newly selected node
            #self.ui.tk_button_stop_dm.config(state="disabled")
            self.ui.tk_label_node_label.config(text="Grid selected.")
            self.selected_nodes = set()

        if self.selected_node and self.selected_node in self.nodes.keys():
            self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="yellow")
            if self.nodes[self.selected_node] not in self.aps:
                if wtn_config.Node_Mode is Node_Mode.UART and self.nodes[self.selected_node].com == "?":
                    self.ui.tk_label_node_label.config(text="Please bind COM.")
                elif wtn_config.Node_Mode is Node_Mode.SOCKET:
                    self.ui.tk_label_node_label.config(text= f"{self.nodes[self.selected_node].com} selected.")

            if self.nodes[self.selected_node].com is not None and self.nodes[self.selected_node].device is not None:
                #self.ui.tk_button_stop_dm.config(state="enabled") 
                self.ui.tk_label_node_label.config(text= f"{self.nodes[self.selected_node].com} selected.")

            if shift_pressed:
                self.selected_nodes.add(self.selected_node)
            else:
                self.selected_nodes = {self.selected_node}
            logging.debug(f"Now selected nodes: {self.selected_nodes}")

            ports = serial.tools.list_ports.comports()
            serial_ports = [port.device for port in ports]
            for node in self.nodes.values():
                if node.com in serial_ports:
                    serial_ports.remove(node.com)

        if self.table_window_id is not None:
            self.ui.tk_canvas_node_grid.delete(self.table_window_id)

        if self.node_info_table_window_id is not None:
            self.ui.tk_canvas_node_grid.delete(self.node_info_table_window_id)
            self.node_info_table_frame = None

        if self.selected_node in self.nodes:
            selected_node = self.nodes[self.selected_node]

            coordinate = self.ui.tk_canvas_node_grid.coords(self.selected_node)
            x, y = coordinate[0], coordinate[1]
            if not self.info_embedded:
                self.create_or_update_node_info_table(self.ui.tk_canvas_node_grid, x, y, selected_node,
                                                      x_offset=20, y_offset=-20)
            self.table_window_id = self.create_table(self.ui.tk_canvas_node_grid, x, y, selected_node.scan_list,
                                                     x_offset=20, y_offset=20)

    def add_ap(self, x, y, mac):
        node_id = self.ui.tk_canvas_node_grid.create_oval(
                (x-0.1) * self.ui.cell_width, (y-0.1) * self.ui.cell_height,
                (x + 2) * self.ui.cell_width, (y + 2) * self.ui.cell_height, fill=AP_COLOR)

        node = Node(node_id, x, y, self.ui)
        node.mac = mac
        self.nodes[node_id] = node
        self.aps.add(node)
        node_text = self.ui.tk_canvas_node_grid.create_text(
            node.x * self.ui.cell_width + self.ui.cell_width * 3,
            node.y * self.ui.cell_height + self.ui.cell_height/2,
            text=node.get_display_text(), fill="black", font=("Arial", 10))
        node.ui = self.ui
        node.node_text = node_text

    def get_ip(self, evt):
        for node in self.nodes.values():
            if node.device:
                # Async execution to prevert UI freeze.
                self.ui.tk_button_get_ip_node.after(0, node.get_ip_and_show)

    def power_save(self, evt):
        for node in self.nodes.values():
            if node.device:
                node.device.start_cmd("AT+WLDBG=wtn wink_en", 0.1)

    # Node selection for multiple purpose
    def select_node_by_com_window(self, filter_func, callback, enable_select_all=False, remote_mode=False):
        # Create a new window
        com_window = tk.Toplevel(self.ui)
        com_window.title("Select Nodes")
        com_window.geometry("400x500")  # Initial size
        com_window.minsize(400, 200)  # Minimum size

        # Create a canvas and a scrollbar
        canvas = tk.Canvas(com_window)
        scrollbar = ttk.Scrollbar(com_window, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Get a list of available nodes
        nodes: List[Node] = self.nodes.values()

        if wtn_config.Node_Mode is Node_Mode.SOCKET:
            nodes = filter(lambda item: item.mac, nodes)
        else:
            nodes = filter(lambda item: item.device, nodes)

        if filter_func:
            nodes = filter(filter_func, nodes)

        nodes = list(nodes)
        if not nodes:
            label = tk.Label(scrollable_frame, text="No node available.")
            label.pack()
            return

        # Create checkboxes for each node
        tk_vars = {}
        columns = 3  # Number of columns
        for index, node in enumerate(nodes):
            var = tk.IntVar()
            identifier = node.mac if wtn_config.Node_Mode is Node_Mode.SOCKET else node.com
            checkbox = tk.Checkbutton(scrollable_frame, text=identifier, variable=var)
            checkbox.grid(row=index // columns, column=index % columns, sticky="w")
            tk_vars[identifier] = var

        # Add "Select All" checkbox if enabled
        if enable_select_all:
            select_all_var = tk.IntVar()
            def toggle_select_all():
                for var in tk_vars.values():
                    var.set(select_all_var.get())

            select_all_checkbox = tk.Checkbutton(scrollable_frame, text="Select All", variable=select_all_var, command=toggle_select_all)
            select_all_checkbox.grid(row=len(nodes) // columns + 1, column=0, columnspan=columns, sticky="w")

        # Create a confirm button
        confirm_button = tk.Button(com_window, text="Confirm",
                                   command=lambda: callback(com_window, nodes, tk_vars))
        confirm_button.pack()

        # Pack the canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Update the window size and center it
        com_window.update_idletasks()
        window_width = max(com_window.winfo_width(), 400)
        window_height = max(com_window.winfo_height(), 500)
        screen_width = com_window.winfo_screenwidth()
        screen_height = com_window.winfo_screenheight()
        position_right = int(screen_width / 2 - window_width / 2)
        position_down = int(screen_height / 2 - window_height / 2)
        com_window.geometry(f"{window_width}x{window_height}+{position_right}+{position_down}")

    def auto_move_select(self, evt):
        def start_auto_move(com_window, nodes, tk_vars):
            com_window.destroy()
            if wtn_config.Node_Mode is Node_Mode.SOCKET:
                selected_nodes = []
            else:
                selected_nodes = [node for node in nodes if tk_vars[node.com].get()]
            for node in selected_nodes:
                if node.id not in self.auto_move_nodes.keys():
                    try:
                        self.auto_move_nodes[node.id] = node
                        if movement_mode == "RANDOM":
                            node.dx, node.dy = self.random_direction(wtn_config.move_speed)
                        self.auto_move(node)
                    except:
                        self.auto_move_nodes.pop(node.id)

        self.select_node_by_com_window(lambda item: item.id not in self.auto_move_nodes.keys(), start_auto_move, enable_select_all=True)

    def stop_move_select(self, evt):
        def stop_auto_move(com_window, nodes, tk_vars):
            com_window.destroy()
            if wtn_config.Node_Mode is Node_Mode.SOCKET:
                selected_nodes = []
            else:
                selected_nodes = [node for node in nodes if tk_vars[node.com].get()]
            for node in selected_nodes:
                if node.id in self.auto_move_nodes.keys():
                    self.auto_move_nodes.pop(node.id)

        self.select_node_by_com_window(lambda item: item.id in self.auto_move_nodes.keys(), stop_auto_move, enable_select_all=True)

    def stop_move_all(self,evt):
        self.auto_move_nodes.clear()

    def ping_select(self, evt):
        def start_ping(com_window, nodes, tk_vars):
            com_window.destroy()
            if wtn_config.Node_Mode is Node_Mode.SOCKET:
                selected_nodes = [node for node in nodes if tk_vars[node.mac].get()]
            else:
                selected_nodes = [node for node in nodes if tk_vars[node.com].get()]
            for node in selected_nodes:
                node.add_ping_monitor()

        self.select_node_by_com_window(lambda item: not item.ping_monitor and item.ip != default_ip, start_ping, enable_select_all=True)

    def stop_ping_select(self, evt):
        def stop_ping(com_window, nodes, tk_vars):
            com_window.destroy()
            if wtn_config.Node_Mode is Node_Mode.SOCKET:
                selected_nodes = [node for node in nodes if tk_vars[node.mac].get()]
            else:
                selected_nodes = [node for node in nodes if tk_vars[node.com].get()]
            for node in selected_nodes:
                if node.ping_monitor:
                    node.stop_ping_and_clear()
                    self.ui.tk_canvas_node_grid.after(100, self.ui.tk_canvas_node_grid.itemconfig(node.ping_text, text=""))

        self.select_node_by_com_window(lambda item: item.ping_monitor and not item.ping_monitor.stop_event.is_set(), stop_ping, enable_select_all=True)

    def reset_ping_results(self, evt):
        for node in list(filter(lambda item: item not in self.aps, self.nodes.values())):
            node.clear_ping_history()
            ping_results.clear()
            self.ui.tk_canvas_node_grid.after(100, self.ui.tk_canvas_node_grid.itemconfig(node.ping_text, text=""))

    def change_ping_interval(self, evt):
        # if any node are pinging.
        pinging_nodes = filter(lambda item: (item.ping_monitor and item.ping_monitor.thread), self.nodes.values())
        pinging_coms = list(map(lambda item: item.com, pinging_nodes))
        if pinging_coms:
            messagebox.showerror("Error", f"Please stop ping {','.join(pinging_coms)} before set interval")
            return
        try:
            new_interval = int(self.ui.tk_input_ping_interval_input.get())
            if new_interval < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please input a positive number as interval")
            return

        wtn_config.ping_interval = new_interval
        self.ui.tk_label_ping_interval_label.config(text=f"Ping interval: {wtn_config.ping_interval} ms.")

    def confirm_selection(self, com_window, serial_ports, vars):
        selected_ports = [port for port in serial_ports if vars[port].get() == 1]
        self.add_node_by_com(selected_ports)

        com_window.destroy()  # Close the window after confirming selection

    def find_location_by_com(self, com_port):
        node_locations_vs_ap = wtn_config.node_locations_vs_ap
        location_index = 0
        for location in node_locations_vs_ap:
            if location[2] == com_port:
                return location_index
            location_index += 1
        return -1

    def find_a_empty_location(self):
        node_locations_vs_ap = wtn_config.node_locations_vs_ap
        location_index = 0
        for location in node_locations_vs_ap:
            if location[2] == 255:
                return location_index
            location_index += 1
        return -1

    def add_remote_node(self, mac, rnat_flag, com=None):
        if self.find_node_by_mac(mac):
            # TODO: -redraw connection
            return
        logging.info(f"添加节点: {mac}")
        max_x = (self.ui.grid_width // self.ui.cell_width) - wtn_config.auto_move_right_margin
        max_y = (self.ui.grid_height // self.ui.cell_height) - wtn_config.auto_move_top_margin
        x = random.randint(5, max_x)
        y = random.randint(5, max_y)

        node_id = None
        if rnat_flag:
            node_id = self.ui.tk_canvas_node_grid.create_rectangle(
                x * self.ui.cell_width, y * self.ui.cell_height,
                (x + 1) * self.ui.cell_width, (y + 1) * self.ui.cell_height, fill="white")
        else:
            node_id = self.ui.tk_canvas_node_grid.create_oval(
                x * self.ui.cell_width, y * self.ui.cell_height,
                (x + 1) * self.ui.cell_width, (y + 1) * self.ui.cell_height, fill="white")

        self.nodes[node_id] = Node(node_id, x, y, self.ui, mac=mac)
        print(f"add remote node {node_id} ({mac})at {x},{y}")
        selected_node = node_id
        node = self.nodes[selected_node]
        if com is not None:
            node.com = com
        if selected_node not in self.nodes:
            return
        if self.nodes[selected_node].node_text is not None:
            self.ui.tk_canvas_node_grid.delete(self.nodes[selected_node].node_text)
        node_text = self.ui.tk_canvas_node_grid.create_text(
            node.x * self.ui.cell_width + self.ui.cell_width * 2,
            node.y * self.ui.cell_height - self.ui.cell_height,
            text=f"{node.get_basic_info_text()}{node.get_suffix()}", fill="black", font=("Arial", 9), anchor='w', angle=PING_TEXT_ANGLE)

        if wtn_config.Node_Mode is ConnectionType.SOCKET and PING_TEXT_ANGLE:
            rect = get_rotated_text_bbox(self.ui.tk_canvas_node_grid, node_text, angle=PING_TEXT_ANGLE)
            init_y = rect[1][1]
        else:
            # Get the bounding box of node_text
            bbox = self.ui.tk_canvas_node_grid.bbox(node_text)

            # Calculate the y position for ping_text based on the bounding box
            # bbox[1] is the top y-coordinate and bbox[3] is the bottom y-coordinate
            init_y = bbox[1]

        ping_text_y = init_y - 15 # Add a small margin (e.g., 15 pixels) to avoid overlap
        # Create the ping_text
        ping_text = self.ui.tk_canvas_node_grid.create_text(
            node.x * self.ui.cell_width + self.ui.cell_width * 2,
            ping_text_y,
            text="", fill="red", font=("Arial", 11, "bold"), anchor='w', angle=PING_TEXT_ANGLE)

        node.ui = self.ui
        node.node_text = node_text
        node.ping_text = ping_text
        self.generate_rssi_table(None, update_ui=False)

    def add_node_by_com(self, selected_ports):
        ap_x = wtn_config.ap_x
        ap_y = wtn_config.ap_y
        max_x = (self.ui.grid_width // self.ui.cell_width) - wtn_config.auto_move_right_margin
        for select_port in selected_ports:
            if select_port.strip() == "AP":
                #self.add_ap(ap_x, ap_y)
                continue

            location_index = self.find_a_empty_location()
            if location_index == -1:
                x = random.randint(5, max_x)
                y = random.randint(5, 55)
            else:
                x = ap_x + node_locations_vs_ap[location_index][0]
                y = ap_y + node_locations_vs_ap[location_index][1]

            node_id = self.ui.tk_canvas_node_grid.create_oval(
                    x * self.ui.cell_width, y * self.ui.cell_height,
                    (x + 1) * self.ui.cell_width, (y + 1) * self.ui.cell_height, fill="white")
            self.nodes[node_id] = Node(node_id, x, y, self.ui)
            threading.Thread(target=self.bind_com_thread, args=(node_id, select_port)).start()

            node_locations_vs_ap[location_index][2] = select_port
            print(f"add node {node_id} at {x},{y} with com {select_port}")

    def mesh_enable(self, evt):
        disabled_nodes = list(filter(lambda item: item.device and not item.mesh_enable, self.nodes.values()))
        for node in disabled_nodes:
            node.device.start_cmd("AT+WLDBG=wtn wtn_en", 0.1)
            node.mesh_enable = True

    def reset_node(self, evt):
        if self.selected_node and self.selected_node in self.nodes.keys():
            node = self.nodes[self.selected_node]
            if (node):
                node.device.start_cmd("reboot", 0.1)
                node.mesh_enable = False

    def power_off_delete_node(self, node, evt=None):
        location_index = -1
        if node in self.aps:
            self.aps.remove(node)

        location_index = self.find_location_by_com(node.com)
        if location_index != -1:
            node_locations_vs_ap[location_index][2] = 255
        print(f"delete node {node.id} at {node.x},{node.y} with com {node.com}")

        self.ui.tk_canvas_node_grid.delete(node.id)
        if node.ping_text:
            self.ui.tk_canvas_node_grid.delete(node.ping_text)
        if node.node_text is not None:
            self.ui.tk_canvas_node_grid.delete(node.node_text)
        if node.relation_line:
                self.ui.tk_canvas_node_grid.delete(node.relation_line)
        if node.secondary_line:
            self.ui.tk_canvas_node_grid.delete(node.secondary_line)
        if node.device is not None:
            node.device.close_com(force=True)
        if node.ping_monitor:
            node.stop_ping_and_clear()
        if node.id in self.auto_move_nodes.keys():
            self.auto_move_nodes.pop(node.id)
        del self.nodes[node.id]
        if node.id == self.log_node:
            self.log_node = None
        self.ui.tk_label_node_label.config(text="")

    def node_power_off_set(self, nodes):
        for node_id, node in nodes.items():
            if node in self.aps:
                ap_id = node_id
                continue
            node.power_off = 1
            #print(f"{node.com} node_power_off_set")
            if node.device is not None:
                node.device.close_com(force=True)

    def power_off_delete_nodes(self, nodes):
        logging.debug(f"power_off_delete_nodes: {",".join(map(lambda node:node.com, nodes.values()))}")
        for node_id, node in nodes.items():
            if node in self.aps:
                ap_id = node_id
                continue

            location_index = self.find_location_by_com(node.com)
            if location_index != -1:
                node_locations_vs_ap[location_index][2] = 255
            print(f"delete node {node.id} at {node.x},{node.y} with com {node.com}")

            self.ui.tk_canvas_node_grid.delete(node_id)
            if node.ping_text:
                self.ui.tk_canvas_node_grid.delete(node.ping_text)
            if node.node_text is not None:
                self.ui.tk_canvas_node_grid.delete(node.node_text)
            if node.relation_line:
                self.ui.tk_canvas_node_grid.delete(node.relation_line)
            if node.secondary_line:
                self.ui.tk_canvas_node_grid.delete(node.secondary_line)
            #if node.device is not None:
            #    node.device.close_com(force=True)
            if node.ping_monitor:
                node.stop_ping_and_clear()
            if node.id in self.auto_move_nodes.keys():
                self.auto_move_nodes.pop(node.id)
            self.nodes.pop(node.id)

        self.ui.tk_label_node_label.config(text="")
        self.generate_rssi_table(None)

    def random_direction(self, speed):
        directions = [
            (speed, 0),
            (-speed, 0),
            (0, speed),
            (0, -speed),
            (speed, speed),
            (speed, -speed),
            (-speed, speed),
            (-speed, -speed)
        ]

        dx, dy = random.choice(directions)

        return dx, dy

    def pace_horizontally(self, node):
        # Ensure the node is within the boundaries
        max_x = (self.ui.grid_width // self.ui.cell_width) - auto_move_right_margin
        max_y = self.ui.grid_height // self.ui.cell_height
        middle_line = max_y // 2

        moved = False

        if node.x < 0:
            node.x = 0
            moved = True
        elif node.x > max_x:
            node.x = max_x
            moved = True

        if node.y < auto_move_top_margin:
            node.y = auto_move_top_margin
            moved = True
        elif node.y > max_y:
            node.y = max_y
            moved = True

        # If the node was moved to the boundary, return its current position
        if moved:
            return node.x, node.y

        # initial state
        if node.dx == 0 and node.dy == 0:
            node.dx = wtn_config.move_speed
            node.dy = 10 if node.y > middle_line else -10

        center_x, center_y = node.x, node.y
        next_x = center_x + node.dx
        next_y = center_y

        # margin -10
        if next_x < 0 or next_x > max_x:
            node.dx = -node.dx
            next_x = center_x
            next_y = center_y + node.dy
            # margin 0 => 10
            if next_y < auto_move_top_margin:
                next_y = auto_move_top_margin
                node.dy = -node.dy  # Reverse vertical direction

            if next_y > max_y:
                next_y = max_y
                node.dy = -node.dy  # Reverse vertical direction

        return next_x, next_y
    
    def auto_move(self, node: Node):
        if wtn_config.Node_Mode == ConnectionType.SOCKET:
            return
        # print(f"move with node {node.mac.split(":")[-1]}")
        if movement_mode == "RANDOM":
            if node.change_direction_interval_counter >= wtn_config.change_direction_move_count:
                node.dx, node.dy = self.random_direction(wtn_config.move_speed)
                node.change_direction_interval_counter = 0
        elif movement_mode == "PACE_HORIZONTALLY":
            next_x, next_y = self.pace_horizontally(node)
        else:
            raise ValueError(f"Unknown movement mode: {node.movement_mode}")

        if movement_mode == "RANDOM":
            center_x, center_y = node.x, node.y
            next_x = center_x + node.dx
            next_y = center_y + node.dy

        # check boundary
        if next_x < 0 or next_x > (self.ui.grid_width // self.ui.cell_width):
            # print("touch horizontal edge")
            node.dx = -node.dx
            next_x = center_x + node.dx

        if next_y < 0 or next_y > (self.ui.grid_height // self.ui.cell_height):
            # print("touch vertical edge")
            node.dy = -node.dy  # Reverse the y direction
            next_y = center_y + node.dy  # Update the target position after reversing

        # Convert virtual coordinates back to actual coordinates and create the event for movement
        event = type('Event', (object,),
                     {'x': next_x, 'y': next_y})()

        # Perform the drag action to move the node
        self.drag_node(event, node)
        self.generate_rssi_table(event)
        # update location
        node.update_position(next_x, next_y)
        node.change_direction_interval_counter += 1

        if node.id in self.auto_move_nodes.keys():
            self.ui.tk_canvas_node_grid.after(wtn_config.auto_move_interval, self.auto_move, node)
        else:
            print(f"stop moving {node}")

    def drag_node(self, event, node=None):
        # remote + manually
        if wtn_config.Node_Mode == ConnectionType.SOCKET and not node and self.auto_layout:
            # drag non-ap node
            if (not self.selected_node or self.selected_node not in self.nodes.keys()
                    or self.nodes[self.selected_node] not in self.aps):
                # handle the case where the key is not present
                logging.warning("dragging node in SOCKET mode.")
                return
            # drag ap node
            selected_node_object = self.nodes[self.selected_node]
            if selected_node_object in self.aps:
                # set should relocate flag for nodes directly under this ap
                for node_id in self.nodes:
                    if self.nodes[node_id].father_node == selected_node_object:
                        self.nodes[node_id].should_relocate = True
            if not wtn_config.ALLOW_DRAG_IN_REMOTE_MODE:
                return

        # for raw input
        # check if the new coordinates are within the grid, if not, cutoff the extra pixels
        x_offset = event.x
        y_offset = event.y
        if not node:
            if event.x < 0:
                x_offset = 0
            elif event.x > self.ui.grid_width - self.ui.cell_width:
                x_offset = self.ui.grid_width - self.ui.cell_width
            if event.y < 0:
                y_offset = 0
            elif event.y > self.ui.grid_height - self.ui.cell_height:
                y_offset = self.ui.grid_height - self.ui.cell_height

        x = x_offset // self.ui.cell_width if not node else x_offset
        y = y_offset // self.ui.cell_height if not node else y_offset
        # self.clear_connection_lines()
        try:
            # Move the com_str text along with the node during dragging
            if (not node) and (not self.selected_node or self.selected_node not in self.nodes):
                return
            target_node_id = node.id if node else self.selected_node
            if self.nodes[target_node_id] in self.aps:
                self.ui.tk_canvas_node_grid.coords(
                target_node_id, (x-0.5) * self.ui.cell_width, (y-0.5) * self.ui.cell_height,
                (x + 1.5) * self.ui.cell_width, (y + 1.5) * self.ui.cell_height)
            else:
                self.ui.tk_canvas_node_grid.coords(
                target_node_id, x * self.ui.cell_width, y * self.ui.cell_height,
                (x + 1) * self.ui.cell_width, (y + 1) * self.ui.cell_height)
            node = self.nodes[target_node_id]
            node.update_position(x, y)
            margin_factor = 2 if wtn_config.Node_Mode == ConnectionType.UART else 0
            if node.node_text is not None:
                if node in self.aps:
                    self.ui.tk_canvas_node_grid.coords(
                    node.node_text, node.x * self.ui.cell_width + self.ui.cell_width * margin_factor,
                    node.y * self.ui.cell_height + self.ui.cell_height/2)
                else:
                    self.ui.tk_canvas_node_grid.coords(
                    node.node_text, node.x * self.ui.cell_width + self.ui.cell_width * margin_factor,
                    node.y * self.ui.cell_height - self.ui.cell_height)
            self.ping_text_layout_auto_adjust(node)
            self.redraw_connection_to_father()
            self.redraw_connection_to_2nd_target()
        except Exception as e:
            traceback.print_exc()

    def ping_text_layout_auto_adjust(self, node):
        if node.ping_text:
            if wtn_config.Node_Mode is ConnectionType.SOCKET and PING_TEXT_ANGLE:
                rect = get_rotated_text_bbox(self.ui.tk_canvas_node_grid, node.node_text, angle=PING_TEXT_ANGLE)
                init_y = rect[1][1]
            else:
                # Get the bounding box of node_text
                bbox = self.ui.tk_canvas_node_grid.bbox(node.node_text)

                # Calculate the y position for ping_text based on the bounding box
                # bbox[1] is the top y-coordinate and bbox[3] is the bottom y-coordinate
                init_y = bbox[1]

            ping_text_y = init_y - self.ui.cell_width * 1  # Add a small margin (e.g., 1 cell width) to avoid overlap
            # Create the ping_text
            self.ui.tk_canvas_node_grid.coords(
                node.ping_text,
                self.ui.cell_width * (node.x + (2 if wtn_config.Node_Mode is ConnectionType.UART else 0)), # match margin factor of node text
                ping_text_y)


    def generate_rssi_table(self,evt,update_ui=True):
        # Clear the table before generating new data
        if update_ui:
            for item in self.ui.tk_canvas_rssi_table.find_all():
                if self.ui.tk_canvas_rssi_table.type(item) == 'text':
                    self.ui.tk_canvas_rssi_table.delete(item)

        grid_size = self.ui.grid_height/self.ui.max_node_count
        # Calculate distances between all pairs of nodes and display node.com in the first row and column
        node_ids = list(self.nodes.keys())
        # Create a header row with node.com
        header_row = [""] + [self.nodes[node_id].get_display_text() for node_id in node_ids]
        for i, header in enumerate(header_row):
            if update_ui:
                self.ui.tk_canvas_rssi_table.create_text(grid_size * i + (grid_size/2), (grid_size/2), text=header, anchor="center",  font=("Arial", 9, "bold"))
        for i, node_id1 in enumerate(node_ids):
            for j, node_id2 in enumerate(node_ids):
                if j == 0:
                    if update_ui:  # Display node.com in the first column
                        self.ui.tk_canvas_rssi_table.create_text((grid_size/2), grid_size * (i + 1) + (grid_size/2), text=self.nodes[node_id1].get_display_text(), anchor="center", font=("Arial", 9, "bold"))
                if i == j:
                    if update_ui:  # Distance to itself is 0
                        self.ui.tk_canvas_rssi_table.create_text(grid_size * (j + 1) + (grid_size/2), grid_size * (i + 1) + (grid_size/2), text="-", anchor="center")
                else:
                    node1 = self.nodes[node_id1]
                    if (node1 == None):
                        break
                    node2 = self.nodes[node_id2]
                    if (node2 == None):
                        break
                    distance = ((node1.x - node2.x) ** 2 + (node1.y - node2.y) ** 2) ** 0.5
                    distance = round(distance, 1) * wtn_config.distance_per_grid
                    try:
                        rssi = wtn_config.get_rssi_by_distance(distance)
                        rssi = round(rssi)
                    except:
                        rssi = 0

                    for wall in self.walls.values():
                        x1 = node1.x * self.ui.cell_width + self.ui.cell_width / 2
                        y1 = node1.y * self.ui.cell_height + self.ui.cell_height / 2
                        x2 = node2.x * self.ui.cell_width + self.ui.cell_width / 2
                        y2 = node2.y * self.ui.cell_height + self.ui.cell_height / 2
                        if wall.check_intersection((x1, y1), (x2, y2)):
                            print(f"wall in {node1.mac} and {node2.mac}")
                            rssi -= wtn_config.wall_attenuation

                    node1.add_item_to_rssi_table((node2.mac, rssi))
                    node2.add_item_to_rssi_table((node1.mac, rssi))
                    if update_ui:
                        self.ui.tk_canvas_rssi_table.create_text(grid_size * (j + 1) + (grid_size/2), grid_size * (i + 1) + (grid_size/2), text=rssi, anchor="center")
        self.need_send_rssi_table = True

    def bind_com_thread(self, selected_node, com_input):
        def update_node_data(name, value, node):
            # print(f"update UI for {name}: {value}")
            setattr(node, name, value), node.refreshUI(embedded=self.info_embedded)
            self.ping_text_layout_auto_adjust(node)

        if selected_node and selected_node in self.nodes.keys():
            if not com_input or com_input == 'com':
                messagebox.showerror("Error", "Invalid COM.")
            else:
                node = self.nodes[selected_node]
                try:
                    device = AmebaDevice(com_input, 1500000, log_callback=node.save_log,
                                         children_update=node.update_children_info,
                                         data_update=lambda name, value: update_node_data(name, value, node))
                    #print(f"open com_input: {com_input} com: {device.com}")
                    node.set_com(com_input)
                    time.sleep(0.2)

                    device.start_cmd("reboot", 0.1)
                    node.set_device(device)
                    self.ui.tk_label_node_label.config(text= f"{node.com} selected.")
                except Exception as e:
                    messagebox.showerror("Error", f"Fail to open com_input: {com_input}")
                    self.power_off_delete_node(node)
                    traceback.print_exc()

                # wait util mac extracted from log
                count = 0
                while node.mac == default_mac and count < 1000:
                    count += 1
                    time.sleep(0.01)

                if selected_node not in self.nodes:
                    return
                if self.nodes[selected_node].node_text is not None:
                    self.ui.tk_canvas_node_grid.delete(self.nodes[selected_node].node_text)
                node_text = self.ui.tk_canvas_node_grid.create_text(
                node.x * self.ui.cell_width + self.ui.cell_width * 2,
                node.y * self.ui.cell_height - self.ui.cell_height,
                text=f"{node.get_basic_info_text()}{node.get_suffix()}" if self.info_embedded else "", fill="black", font=("Arial", 9), anchor='w')

                # Get the bounding box of node_text
                bbox = self.ui.tk_canvas_node_grid.bbox(node_text)

                # Calculate the y position for ping_text based on the bounding box
                # bbox[1] is the top y-coordinate and bbox[3] is the bottom y-coordinate
                ping_text_y = bbox[1] - 15  # Add a small margin (e.g., 5 pixels) to avoid overlap

                # Create the ping_text
                ping_text = self.ui.tk_canvas_node_grid.create_text(
                    node.x * self.ui.cell_width + self.ui.cell_width * 2,
                    ping_text_y,
                    text="", fill="red", font=("Arial", 11, "bold"), anchor='w')

                node.ui = self.ui
                node.node_text = node_text
                node.ping_text = ping_text

                self.generate_rssi_table(None, update_ui = False)

                send_rssi_cmds = node.get_fix_rssi_str()
                if send_rssi_cmds and send_rssi_cmds != []:
                    for cmd in send_rssi_cmds:
                        if device:
                            device.start_cmd(cmd, 0.05)
                        else:
                            print("device does not exist")

                #device.start_cmd("wtn wtn_en", 0.01)
                #time.sleep(0.01)
                #device.start_cmd("wtn wtn_en", 0.01)
                #time.sleep(0.01)

                if (wtn_config.first_link_ap):
                    time.sleep(1)
                    device.start_cmd(f"AT+WLCONN=ssid,{ssid},pw,{password}", 7) # reconnect when fast connect open

    def update_node_color(self, selected_node, change_selected=0):
        if selected_node and selected_node in self.nodes.keys():
            node = self.nodes[selected_node]
            # Highlight
            if self.highlight_node_mac and self.highlight_node_mac in node.mac.replace(":", "").lower():
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill=node_highlight_color)
                return
            # Selected Node
            if selected_node in self.selected_nodes:
                if change_selected:
                    self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="yellow")
                return
            # Get color from color manager
            custom_color = self.color_manager.get_color_by_mac(node.mac)
            if custom_color is not None:
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill=custom_color)
                return
            if node in self.aps:
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill=AP_COLOR)
            elif node.father_mac == default_mac and node.bssid == default_mac:
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill="white")
            elif node.bssid == default_mac:
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill="#FDE599")
            elif node.father_mac == default_mac:
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill="white")
            else:
                self.ui.tk_canvas_node_grid.itemconfig(selected_node, fill=node.node_color())

    def save_log(self, evt):
        def set_file_for_node(com_window, nodes, tk_vars):
            com_window.destroy()
            if wtn_config.Node_Mode is Node_Mode.SOCKET:
                selected_nodes = [node for node in nodes if tk_vars[node.mac].get()]
            else:
                selected_nodes = [node for node in nodes if tk_vars[node.com].get()]
            save_file(selected_nodes)

        self.select_node_by_com_window(None,set_file_for_node)

    def send_rssi_table(self,evt):
        self.need_send_rssi_table = False
        for key in list(self.nodes.keys()):
            node = self.nodes[key]
            if node is None:
                break
            if node.power_off:
                break
            if node.device is not None:
                fix_rssi_str_list = node.get_fix_rssi_str()
                for fix_rssi_str in fix_rssi_str_list:
                    if node != None and node.power_off == 0 and node.device is not None:
                        node.device.start_cmd(fix_rssi_str, 0.02, node)

        # self.draw_connection_to_father()

    def select_cmd(self,evt):
        selected_index = self.ui.tk_list_box_cmd_list.curselection()
        if selected_index:
            selected_value = self.ui.tk_list_box_cmd_list.get(selected_index)
            self.ui.tk_input_cmd_input.delete(0, tk.END)
            self.ui.tk_input_cmd_input.insert(0, selected_value)


    def double_select_cmd(self,evt):
        self.input_cmd(evt)

    def input_cmd(self,evt):
        if not self.log_node or self.log_node not in self.nodes.keys():
            self.ui.tk_input_cmd_input.delete(0, tk.END)
            return
        cmd_input = self.ui.tk_input_cmd_input.get()
        if not cmd_input:
            return
        node = self.nodes[self.log_node]
        if node.device is None:
            self.ui.tk_input_cmd_input.delete(0, tk.END)
            return
        node.device.start_cmd(cmd_input.strip(),0)
        # self.ui.tk_text_output.insert(tk.END, result)
        # self.ui.tk_text_output.see(tk.END)
        self.ui.tk_input_cmd_input.delete(0, tk.END)
        if cmd_input not in self.ui.tk_list_box_cmd_list.get(0, tk.END):
            self.ui.tk_list_box_cmd_list.insert(tk.END, cmd_input)
        elif cmd_input in self.ui.tk_list_box_cmd_list.get(0, tk.END):
            index = self.ui.tk_list_box_cmd_list.get(0, tk.END).index(cmd_input)
            self.ui.tk_list_box_cmd_list.delete(index)
            self.ui.tk_list_box_cmd_list.insert(tk.END, cmd_input)

    def init_network(self,evt):
        self.draw_connection_to_father()
        self.draw_connection_to_2nd_target()

    def change_distance(self,evt):
        try:
            new_distance = float(self.ui.tk_input_dis_input.get())
        except ValueError:
            messagebox.showerror("Error", "Please input a number as distance")
            return
        
        wtn_config.distance_per_grid = new_distance
        self.ui.tk_label_dis_label.config(text=f"The distance of each grid is set to {wtn_config.distance_per_grid} m.")
        self.generate_rssi_table(evt)

    def change_ping_window_size(self,evt):
        try:
            ping_rtt_aver_window_size = int(self.ui.tk_input_ping_window_size_input.get())
        except ValueError:
            messagebox.showerror("Error", "Please input a integer number as window size")
            return

        wtn_config.ping_rtt_aver_window_size = ping_rtt_aver_window_size
        self.ui.tk_label_ping_window_size_label.config(text=f"The ping delay window size is set to {wtn_config.ping_rtt_aver_window_size} .")

    def get_output(self):
        if not self.selected_node or self.selected_node not in self.nodes.keys():
            print("not output: "+self.selected_node)
            return
        node = self.nodes[self.selected_node]
        if (node == None or node.power_off == 1):
            return
        if not node.device:
            return
        
        last_output_time = time.time()
        while True:
            output = node.device.get_output()
            if output:
                self.ui.tk_text_output.insert(tk.END, output)
                self.ui.tk_text_output.see(tk.END)
                last_output_time = time.time()
            else:
                if time.time() - last_output_time > 1.5:
                    break
            time.sleep(0.2)

    def redraw_connection_to_father(self):
        for key in list(self.nodes.keys()):
            node = self.nodes[key]
            if node and node.relation_line is not None and node.father_node is not None:
                self.ui.tk_canvas_node_grid.coords(
                    node.relation_line,
                    node.x * self.ui.cell_width + self.ui.cell_width / 2, 
                    node.y * self.ui.cell_height + self.ui.cell_height / 2, 
                    node.father_node.x * self.ui.cell_width + self.ui.cell_width / 2, 
                    node.father_node.y * self.ui.cell_height + self.ui.cell_height / 2
                )

    def draw_connection_to_father(self):
        mac_to_node = {n.mac: n for n in self.nodes.values()}
        for key in list(self.nodes.keys()):
            if key not in self.nodes.keys(): # avoid concurrent modify
                continue
            node = self.nodes[key]
            if node:
                self.update_node_color(key)
            if not node.online:
                continue

            if node and node.father_mac and node.father_mac != default_mac:
                father_node = mac_to_node.get(node.father_mac)
                bssid_check_required = not wtn_config.RNAT_ENABLE
                bssid_not_in_ap_list = node.bssid not in wtn_config.ap_mac_list
                if not father_node or (bssid_check_required and bssid_not_in_ap_list):
                    if node.relation_line is not None:
                        self.ui.tk_canvas_node_grid.delete(node.relation_line)
                        node.relation_line = None
                    if node.relation_line_mark:
                        self.ui.tk_canvas_node_grid.delete(node.relation_line_mark)
                        node.relation_line_mark = None
                    continue

                node.father_node = father_node
                if node.relation_line is not None:
                    self.ui.tk_canvas_node_grid.coords(
                        node.relation_line,
                        node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        node.y * self.ui.cell_height + self.ui.cell_height / 2,
                        father_node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        father_node.y * self.ui.cell_height + self.ui.cell_height / 2
                    )
                else:
                    node.relation_line = self.ui.tk_canvas_node_grid.create_line(
                            node.x * self.ui.cell_width + self.ui.cell_width / 2, 
                            node.y * self.ui.cell_height + self.ui.cell_height / 2, 
                            father_node.x * self.ui.cell_width + self.ui.cell_width / 2, 
                            father_node.y * self.ui.cell_height + self.ui.cell_height / 2, 
                            fill="blue", arrow=tk.LAST)
                if node.relation_line is not None and node.score:
                    try:
                        scores = node.score.split(', ')
                        father_part = scores[0] if len(scores) > 0 else None
                        candidate_part = scores[1] if len(scores) > 1 else None
                        mac, score = father_part[:2], father_part[2:]
                        mac = mac.strip()
                        if candidate_part:
                            score += f"/{candidate_part[2:]}"

                        dx = father_node.x - node.x
                        dy = father_node.y - node.y
                        length = (dx ** 2 + dy ** 2) ** 0.5
                        unit_dx = dx / length
                        unit_dy = dy / length

                        source_x = node.x * self.ui.cell_width + self.ui.cell_width / 2
                        source_y = node.y * self.ui.cell_height + self.ui.cell_height / 2
                        offset_distance = 20
                        extra_offset_x = 10 if unit_dx >= 0 else -10
                        extra_offset_y = 10 if unit_dy >= 0 else -10

                        offset_x = unit_dx * offset_distance + extra_offset_x
                        offset_y = unit_dy * offset_distance + extra_offset_y

                        angle = math.degrees(math.atan2(dy, dx))
                        if angle < -90 or angle > 90:
                            angle += 180
                        angle = -angle

                        if node.relation_line_mark is not None:
                            self.ui.tk_canvas_node_grid.coords(node.relation_line_mark, source_x + offset_x,
                                                               source_y + offset_y)
                            self.ui.tk_canvas_node_grid.itemconfig(node.relation_line_mark, text=f"{score}",
                                                                   angle=angle)
                        elif wtn_config.Node_Mode == ConnectionType.SOCKET:
                            node.relation_line_mark = self.ui.tk_canvas_node_grid.create_text(source_x + offset_x,
                                                                                              source_y + offset_y,
                                                                                              text=f"{score}",
                                                                                              fill="red", angle=angle)
                    except ValueError:
                        pass
                else:
                    node.relation_line_mark = None

                self.ui.tk_canvas_node_grid.tag_raise(node.relation_line)
                if node.relation_line_mark:
                    self.ui.tk_canvas_node_grid.tag_raise(node.relation_line_mark)

    def draw_connection_to_2nd_target(self):
        for key in list(self.nodes.keys()):
            node = self.nodes[key]
            if node == None:
                continue

            self.update_node_color(key)
            if not node.online:
                continue

            if node.score:
                try:
                    scores = node.score.split(', ')
                    if len(scores) < 2:
                        continue
                    father_part = scores[0] if len(scores) > 0 else None
                    candidate_part = scores[1] if len(scores) > 1 else None
                    mac, score = candidate_part[:2], candidate_part[2:]
                    mac = mac.strip()
                except ValueError:
                    continue

                target_node = None
                for n in self.nodes.values():
                    if n.mac.lower().endswith(mac.lower()):
                        target_node = n
                        break

                if not target_node:
                    if node.secondary_line is not None:
                        self.ui.tk_canvas_node_grid.delete(node.secondary_line)
                        node.secondary_line = None
                    # if node.secondary_line_mark:
                    #     self.ui.tk_canvas_node_grid.delete(node.secondary_line_mark)
                    #     node.secondary_line_mark = None
                    continue

                if node.secondary_line is not None:
                    self.ui.tk_canvas_node_grid.coords(
                        node.secondary_line,
                        node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        node.y * self.ui.cell_height + self.ui.cell_height / 2,
                        target_node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        target_node.y * self.ui.cell_height + self.ui.cell_height / 2
                    )
                else:
                    node.secondary_line = self.ui.tk_canvas_node_grid.create_line(
                        node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        node.y * self.ui.cell_height + self.ui.cell_height / 2,
                        target_node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        target_node.y * self.ui.cell_height + self.ui.cell_height / 2,
                        fill="gray", dash=(4, 2), arrow=tk.LAST
                    )

                if node.secondary_line is not None and node.score:
                    scores = node.score.split(', ')
                    father_part = scores[0] if len(scores) > 0 else None
                    candidate_part = scores[1] if len(scores) > 1 else None
                    mac, score = candidate_part[:2], candidate_part[2:]
                    mac = mac.strip()

                    dx = target_node.x - node.x
                    dy = target_node.y - node.y
                    length = (dx**2 + dy**2)**0.5
                    unit_dx = dx / length
                    unit_dy = dy / length

                    source_x = node.x * self.ui.cell_width + self.ui.cell_width / 2
                    source_y = node.y * self.ui.cell_height + self.ui.cell_height / 2
                    offset_distance = 35
                    extra_offset_x = 10 if unit_dx >= 0 else -10
                    extra_offset_y = 10 if unit_dy >= 0 else -10

                    offset_x = unit_dx * offset_distance + extra_offset_x
                    offset_y = unit_dy * offset_distance + extra_offset_y


                #     if node.secondary_line_mark:
                #         self.ui.tk_canvas_node_grid.coords(node.secondary_line_mark, source_x + offset_x, source_y + offset_y)
                #         self.ui.tk_canvas_node_grid.itemconfig(node.secondary_line_mark, text=f"{score}")
                #     elif wtn_config.Node_Mode == ConnectionType.SOCKET:
                #         node.secondary_line_mark = self.ui.tk_canvas_node_grid.create_text(source_x + offset_x, source_y + offset_y, text=f"{score}", fill="gray")
                # else:
                #     node.secondary_line_mark = None

                self.ui.tk_canvas_node_grid.tag_raise(node.secondary_line)
                # if node.secondary_line_mark:
                #     self.ui.tk_canvas_node_grid.tag_raise(node.secondary_line_mark)

    def redraw_connection_to_2nd_target(self):
        for key in list(self.nodes.keys()):
            node = self.nodes[key]
            if node and node.secondary_line is not None and node.score:
                try:
                    _, second_part = node.score.split(', ')
                    mac, score = second_part[:2], second_part[2:]
                    mac = mac.strip()
                except ValueError:
                    continue

                target_node = None
                for n in self.nodes.values():
                    if n.mac.lower().endswith(mac.lower()):
                        target_node = n
                        break

                if target_node:
                    self.ui.tk_canvas_node_grid.coords(
                        node.secondary_line,
                        node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        node.y * self.ui.cell_height + self.ui.cell_height / 2,
                        target_node.x * self.ui.cell_width + self.ui.cell_width / 2,
                        target_node.y * self.ui.cell_height + self.ui.cell_height / 2
                    )

    def clear_connect_lines_and_marks_for(self, node):
        if node.relation_line:
            self.ui.tk_canvas_node_grid.delete(node.relation_line)
            node.relation_line = None
        if node.relation_line_mark:
            self.ui.tk_canvas_node_grid.delete(node.relation_line_mark)
            node.relation_line_mark = None
        if node.secondary_line:
            self.ui.tk_canvas_node_grid.delete(node.secondary_line)
            node.secondary_line = None
        # if node.secondary_line_mark:
        #     self.ui.tk_canvas_node_grid.delete(node.secondary_line_mark)
        #     node.secondary_line_mark = None

    def clear_connection_lines(self):
        for node in self.nodes.values():
            self.clear_connect_lines_and_marks_for(node)

    # TODO:- Only update score instead of redraw all links periodically for better performance
    def update_score(self, node):
        if score := node.get_score_to(node.father_mac) and node.relation_line_mark:
            self.ui.tk_canvas_node_grid.itemconfig(node.relation_line_mark, text=f"score:{score}")
        # if score := node.get_score_to(node.get_candidate_mac()) and node.secondary_line_mark:
        #     self.ui.tk_canvas_node_grid.itemconfig(node.secondary_line_mark, text=f"score:{score}")

    def read_device_output_thread(self):
        while self.thread_status:
            for key in list(self.nodes.keys()):
                try:
                    if key not in self.nodes.keys():
                        continue
                    node = self.nodes[key]
                    if node and node.device and node.power_off == 0:
                        output = node.device.get_output()
                        if not output or output == "":
                            continue
                        if self.log_node and key == self.log_node:
                            if len(self.ui.tk_text_output.get("1.0", "end-1c").split('\n')) > 100:
                                self.ui.tk_text_output.delete("1.0", "2.0")
                            self.ui.tk_text_output.insert(tk.END, output)
                            self.ui.tk_text_output.see(tk.END)
                except Exception as e:
                    print(e)
            time.sleep(0.5)  # Sleep for a short period to avoid overloading the device

    def refresh_relation_thread(self):
        time.sleep(5)
        print("refresh_relation_thread start")
        while self.thread_status:
            try:
                if self.need_send_rssi_table:
                    self.send_rssi_table(None)
                self.draw_connection_to_father()
                self.draw_connection_to_2nd_target()
            except Exception as e:
                #print(f"SerialException3: {e}")
                #traceback.print_exc()
                time.sleep(0.1)
            time.sleep(0.5)


    def add_wall(self, evt):
        self.in_add_wall = True
        self.ui.tk_button_add_wall.config(state=tk.DISABLED)  # Disable the add_wall button


    def remove_wall(self, evt):
        if self.selected_wall and self.selected_wall in self.walls:
            self.ui.tk_canvas_node_grid.delete(self.selected_wall)
            del self.walls[self.selected_wall] 
            self.generate_rssi_table(evt)

    def select_wall(self, evt):
        select_grids = self.ui.tk_canvas_node_grid.find_closest(evt.x, evt.y)
        select_grid = None
        for grid in select_grids:
            if self.ui.tk_canvas_node_grid.type(grid) == 'rectangle':  # Check if select_grid exists
                select_grid = grid
                break
            # select_grid = self.ui.tk_canvas_node_grid.find_closest(evt.x, evt.y, halo=5)[0]
        print(select_grid)
        if select_grid is None:
            return
        x = select_grid // self.ui.rows
        y = select_grid % self.ui.rows - 1
        if y < 0:
            x -= 1
            y = self.ui.rows - 1

        if self.start_point is None:
            center_x = x * self.ui.cell_width + self.ui.cell_width / 2
            center_y = y * self.ui.cell_height + self.ui.cell_height / 2
            self.start_point = (center_x, center_y)
            if self.selected_node and self.ui.tk_canvas_node_grid.type(self.selected_node) == 'rectangle':
                self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="#e0e0e0")
            self.selected_node = select_grid
            self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="yellow")
        else:
            center_x = x * self.ui.cell_width + self.ui.cell_width / 2
            center_y = y * self.ui.cell_height + self.ui.cell_height / 2
            end_point = (center_x, center_y)
            wall_node = self.ui.tk_canvas_node_grid.create_line(
                self.start_point[0], self.start_point[1], end_point[0], end_point[1], width=self.ui.cell_width, fill="dark gray"
            )
            wall = Wall(self.start_point, end_point)
            self.walls[wall_node] = wall
            self.start_point = None
            self.in_add_wall = False
            if self.selected_node:
                self.ui.tk_canvas_node_grid.itemconfig(self.selected_node, fill="#e0e0e0")
            self.selected_node = None
            self.ui.tk_button_add_wall.config(state="enabled") # Disable the add_wall button
            self.generate_rssi_table(evt)

    def drag_wall(self, evt):
        self.in_add_wall = False

    def set_connection_to_uart(self, evt):
        self.update_node_mode(ConnectionType.UART.value)

    def set_connection_to_remote(self, evt):
        self.update_node_mode(ConnectionType.SOCKET.value)

    def auto_layout_toggle(self, value: bool):
        self.auto_layout = value
        if value:
            for node in self.nodes.values():
                node.should_relocate = True

    def info_embedded_toggle(self, value: bool):
        self.info_embedded = value
        if self.info_embedded and self.node_info_table_window_id is not None:
            self.ui.tk_canvas_node_grid.delete(self.node_info_table_window_id)
            self.node_info_table_frame = None

    def update_node_mode(self, mode):
        """
        Update the node mode in the configuration file.

        :param mode: The new mode to set for Node_Mode.
        """
        # Assuming 'Node_Mode' is a top-level key in the configuration
        update_config_key('basic.node_mode', f'{mode}')


def get_rotated_text_bbox(canvas, text_id, angle):

    def rotate_point(x, y, angle, cx, cy):
        radians = math.radians(angle)
        cos_val = math.cos(radians)
        sin_val = math.sin(radians)
        nx = cos_val * (x - cx) - sin_val * (y - cy) + cx
        ny = sin_val * (x - cx) + cos_val * (y - cy) + cy
        return nx, ny

    bbox = canvas.bbox(text_id)

    x1, y1, x2, y2 = bbox
    vertices = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

    # center coordinate
    cx, cy = canvas.coords(text_id)

    rotated_vertices = [rotate_point(x, y, angle, cx, cy) for x, y in vertices]

    return rotated_vertices
