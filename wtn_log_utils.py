import os
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox as messagebox

from wtn_node import Node


def save_file(nodes: [Node]):
    base_file_path = filedialog.asksaveasfilename(defaultextension=".txt",
                                                  filetypes=[("Log files", "*.log"),
                                                             ("Text files", "*.txt"),
                                                             ("All files", "*.*")])
    if base_file_path:
        base_name = os.path.splitext(base_file_path)[0]
        directory = os.path.dirname(base_file_path)
        info_file = []
        for node in nodes:
            node.log_file = os.path.join(directory,
                                         f"{base_name}_{node.com}_{node.mac.split(':')[-1]}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.txt")

        # 创建这些文件但不写入内容
        for file_path in map(lambda node: node.log_file, nodes):
            with open(file_path, 'w'):
                pass
            print(f"Node {node.com} file created at: {file_path}")
    else:
        messagebox.showerror("Error", "Please choose a file to save logs.")
        return


def delete_old_files(directory, ten_minutes):
    now = datetime.now()
    cutoff = now - timedelta(minutes=10 * ten_minutes)

    # Traverse files in the directory
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.startswith("NodeActivities"):
                continue
            file_path = os.path.join(root, file)
            # Get the last modified time of the file
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))

            if file_mtime < cutoff:
                print(f"Deleting: {file_path}")
                os.remove(file_path)
