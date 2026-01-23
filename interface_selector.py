import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import psutil
import socket
import logging

from utils import resource_path

logging.basicConfig(level=logging.INFO)


def get_interfaces():
    """
    遍历所有网络接口，返回接口列表
    """
    interfaces = []
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                interfaces.append(iface)
                break
    return interfaces


class InterfaceSelector(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("选择网络接口")
        self.geometry("400x200")
        self.resizable(False, False)

        self.style = ttk.Style(self)
        self.style.theme_use('clam')

        self.selected_interface = tk.StringVar(self)

        main_frame = ttk.Frame(self, padding="20 20 20 20")
        main_frame.grid(column=0, row=0, sticky=(tk.N, tk.E, tk.S, tk.W))

        ttk.Label(main_frame, text="请选择一个网络接口：", font=("Helvetica", 12)).grid(column=0, row=0, columnspan=2,
                                                                                       pady=(0, 10))

        # 网络接口列表（Combobox）
        self.interface_combobox = ttk.Combobox(main_frame, textvariable=self.selected_interface, state="readonly",
                                               width=30)
        self.interface_combobox.grid(column=0, row=1, columnspan=2, pady=(0, 10))

        # 刷新按钮，便于更新网络列表
        refresh_button = ttk.Button(main_frame, text="刷新列表", command=self.refresh_interfaces)
        refresh_button.grid(column=0, row=2, padx=(0, 10), pady=(0, 20), sticky=tk.E)

        # 确认按钮
        confirm_button = ttk.Button(main_frame, text="确定", command=self.on_confirm)
        confirm_button.grid(column=1, row=2, pady=(0, 20), sticky=tk.W)

        # 布局设置
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # 加载接口列表
        self.refresh_interfaces()

    def refresh_interfaces(self):
        """
        刷新网络接口列表
        """
        interfaces = get_interfaces()
        if not interfaces:
            messagebox.showerror("错误", "没有找到符合条件的网络接口")
            self.destroy()  # 结束窗口并退出
            return
        self.interface_combobox['values'] = interfaces
        # 如果当前选项不在接口列表中，默认选中第一个
        if self.selected_interface.get() not in interfaces:
            self.selected_interface.set(interfaces[0])
        logging.info("刷新网络接口列表：%s", interfaces)

    def on_confirm(self):
        """
        确认选择的网络接口
        """
        chosen_iface = self.selected_interface.get()
        if not chosen_iface:
            messagebox.showwarning("警告", "请选择一个网络接口")
            return
        logging.info("用户选择的接口：%s", chosen_iface)
        self.destroy()  # 关闭窗口


def launch_interface_selection():
    """
    打开接口选择窗口，返回选择的接口
    """
    app = InterfaceSelector()
    app.title("Gravitation")
    icon_path = resource_path("black-hole.png")
    icon_image = tk.PhotoImage(file=icon_path)
    app.iconphoto(True, icon_image)
    app.mainloop()
    return app.selected_interface.get()
