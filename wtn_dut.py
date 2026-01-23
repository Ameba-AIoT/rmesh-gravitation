import logging
import re
import time

import serial
from wtn_config import *
import traceback
import threading
import os

default_mac = '00:00:00:00:00:00'
class AmebaDevice:
    def __init__(self, com, baud=1500000, timeout = 0.5, log_callback=None, children_update=None, data_update=None):
        self.com = com
        self.baud = baud
        self.status = True
        self.open_com = serial.Serial(self.com, self.baud, timeout = 1)
        self.last_output = ""
        self.log_callback = log_callback
        self.children_update = children_update
        self.data_update = data_update
        self.force_to_close = False
        self.serial_lock = threading.Lock()

    def start_cmd(self, cmd, time_wait=0.2, node=None):
        try:
            with self.serial_lock:
                if self.open_com.is_open:
                    self.open_com.write(f'{cmd}\r\n'.encode())
            time.sleep(time_wait)
            self.status = True
        except serial.serialutil.SerialTimeoutException:
            print(f"{self.com} SerialException1:")
            if not self.force_to_close:
                self.force_to_close = True
            if (node != None):
                node.power_off = 1
        except serial.serialutil.SerialException as e:  # Catch SerialTimeoutException here
            self.status = False
            if not self.force_to_close:
                print(f"{self.com} SerialException: {e}")
                print(f"{self.com} SerialException: cmd: {cmd} timeout: {time_wait}")
                self.force_to_close = True
                if (node != None):
                    node.power_off = 1
        except Exception as e:
            print(f"{self.com} SerialException2: {e}")
            self.force_to_close = True
            if (node != None):
                node.power_off = 1
            traceback.print_exc()

    def resolve_out_put(self, text):
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
        if self.children_update:
            match = re.search(r"(child-\d+:[\w/]*)", text)
            if match:
                self.children_update(match.group(1).strip())
        if self.data_update:
            for name, regex in regex_rules.items():
                match = re.search(regex, text)
                if match:
                    self.data_update(name, match.group(1).strip())

    def get_output(self):
        result = ""
        if self == None or self.force_to_close:
            return None
        try:
            start_time = time.perf_counter()
            logging.debug(f"Time start read: {start_time:.6f} seconds")
            with self.serial_lock:
                self.open_com.timeout = 1
                result = self.open_com.read(self.open_com.in_waiting)
            read_time = time.perf_counter() - start_time
            if read_time > 0.1:
                print(f"Read time is too long: {read_time:.6f} seconds")
            else:
                logging.debug(f"Time taken for read: {read_time:.6f} seconds")

            start_time = time.perf_counter()
            logging.debug(f"Time start decode: {start_time:.6f} seconds")
            result = result.decode(encoding="ascii", errors="ignore")
            decode_time = time.perf_counter() - start_time
            if decode_time > 0.1:
                print(f"Time taken for decode: {decode_time:.6f} seconds")
            else:
                logging.debug(f"Time taken for decode: {decode_time:.6f} seconds")

            if result:
                self.last_output = result
                for line in result.splitlines():
                    content = line.strip()
                    if content and (content.startswith("[TN-I] gravitation show") or content.startswith("Interface")):
                        start_time = time.perf_counter()
                        self.resolve_out_put(content)
                        resolve_time = time.perf_counter() - start_time
                        logging.debug(f"Time taken for resolve_out_put: {resolve_time:.6f} seconds")

                if self.log_callback:
                    start_time = time.perf_counter()
                    self.log_callback(result)
                    log_callback_time = time.perf_counter() - start_time
                    logging.debug(f"Time taken for log_callback: {log_callback_time:.6f} seconds")

            self.status = True
        except serial.serialutil.SerialTimeoutException:
            if not self.force_to_close:
                logging.debug("SerialTimeoutException occurred, sleeping for 0.1 seconds")
                self.force_to_close = True
                time.sleep(0.1)
        except serial.serialutil.SerialException as e:
            self.status = False
            if not self.force_to_close:
                exception_time = time.perf_counter() - start_time
                logging.error(f"{self.com} SerialException4: {e}")
                logging.debug(f"Time taken before SerialException: {exception_time:.6f} seconds")
                self.force_to_close=True
        except Exception as e:
            exception_time = time.perf_counter() - start_time
            logging.error(f"Unexpected error: {e}")
            logging.debug(f"Time taken before Exception: {exception_time:.6f} seconds")
            traceback.print_exc()
            self.force_to_close=True
        return result

    def get_mac(self):
        self.start_cmd('AT+WLSTATE')
        result = self.get_output()
        if not result or result == "":
            result = self.last_output
        mac_pattern = r'MAC => (\w{2}:\w{2}:\w{2}:\w{2}:\w{2}:\w{2})'
        mac_match = re.search(mac_pattern, result)
        mac = default_mac
        if mac_match:
            mac = mac_match.group(1)
        return mac

    def get_ip(self):
        self.start_cmd('AT+WLSTATE')
        result = self.get_output()
        if not result or result == "":
            result = self.last_output
        ip_pattern = r'IP\s*=>\s*(\b(?:\d{1,3}\.){3}\d{1,3}\b)'
        ips = re.findall(ip_pattern, result)
        if ips:
            return ips[0]
        return None

    def close_com(self, force = False):
        with self.serial_lock:
            self.open_com.close()
        if force == True:
            self.force_to_close = True
            #self.thread.join()

if __name__ == '__main__':
    dut = AmebaDevice('COM48', 1500000)