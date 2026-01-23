import logging
from tkinter import *
from tkinter import ttk
from tkinter.ttk import *

import wtn_config as wtn_config
from entry_with_placeholder import EntryWithPlaceholder
from ota_updater import OTAUpgradeTab
from enums import ConnectionType


class WinGUI(Tk):
    def __init__(self):
        super().__init__()
        self.show_panel = True
        self.all_grid_components = []
        self.__win()
        self.max_node_count = 20
        self.grid_size = 12
        self.grid_width = self.winfo_screenwidth() - 620
        self.grid_height = self.winfo_screenheight() - 150
        self.config_input_y = self.winfo_screenheight() - 130
        self.button_x = self.winfo_screenwidth() - 120
        self.button_y = self.config_input_y - 40
        self.rows = self.grid_height // self.grid_size
        self.cols = self.grid_width // self.grid_size
        self.cell_width = self.grid_size
        self.cell_height = self.grid_size
        self.tk_tabs_tab = self.__tk_tabs_tab(self)
        self.tk_canvas_node_grid = self.__tk_canvas_node_grid( self.tk_tabs_tab_0)
        self.tk_canvas_rssi_table = self.__tk_canvas_rssi_table( self.tk_tabs_tab_1)
        self.tk_text_output, self.tk_output_scrollBar, self.text_frame = self.__tk_text_output( self.tk_tabs_tab_0)
        self.tk_input_cmd_input = self.__tk_input_cmd_input( self.tk_tabs_tab_0)
        self.tk_list_box_cmd_list = self.__tk_list_box_cmd_list( self.tk_tabs_tab_0)
        self.tk_button_ping = self.__tk_button_ping(self.tk_tabs_tab_0)
        self.tk_button_stop_ping = self.__tk_button_stop_ping(self.tk_tabs_tab_0)
        self.tk_button_reset_ping_results = self.__tk_button_reset_ping_results(self.tk_tabs_tab_0)
        self.tk_button_toggle_panel = self.__tk_button_toggle_panel(self.tk_tabs_tab_0)
        self.tk_highlight_node_mac_input = self.__tk_highlight_node_mac_input(self.tk_tabs_tab_0)
        self.tk_button_power_save = self.__tk_button_power_save( self.tk_tabs_tab_0)
        self.tk_label_node_label = self.__tk_label_node_label( self.tk_tabs_tab_0)
        self.tk_label_ping_interval_label = self.__tk_label_ping_interval_label(self.tk_tabs_tab_0)
        self.tk_input_ping_interval_input = self.__tk_input_ping_interval_input(self.tk_tabs_tab_0)
        self.tk_button_change_ping_interval = self.__tk_button_change_ping_interval(self.tk_tabs_tab_0)
        #self.tk_button_add_wall = self.__tk_button_add_wall(self.tk_tabs_tab_0)
        #self.tk_button_remove_wall = self.__tk_button_remove_wall(self.tk_tabs_tab_0)
        self.tk_checkbox_auto_layout = self.__tk_checkbox_auto_layout( self.tk_tabs_tab_0)
        self.tk_checkbox_show_info_embedded = self.__tk_checkbox_show_info_embedded(self.tk_tabs_tab_0)
        # only for uart mode
        if not wtn_config.Node_Mode == ConnectionType.SOCKET:
            self.tk_button_mesh_enable_node = self.__tk_button_mesh_enable_node(self.tk_tabs_tab_0)
            self.tk_button_reset_node = self.__tk_button_reset_node(self.tk_tabs_tab_0)
            self.tk_button_auto_move = self.__tk_button_auto_move(self.tk_tabs_tab_0)
            self.tk_button_stop_move = self.__tk_button_stop_move(self.tk_tabs_tab_0)
            # stop moving button
            self.tk_button_stop_all = self.__tk_button_stop_all(self.tk_tabs_tab_0)
            self.tk_label_dis_label = self.__tk_label_dis_label(self.tk_tabs_tab_0)
            self.tk_input_dis_input = self.__tk_input_dis_input(self.tk_tabs_tab_0)
            self.tk_button_change_dis = self.__tk_button_change_dis(self.tk_tabs_tab_0)
            self.tk_label_ping_window_size_label = self.__tk_label_ping_window_size_label(self.tk_tabs_tab_0)
            self.tk_input_ping_window_size_input = self.__tk_input_ping_window_size_input(self.tk_tabs_tab_0)
            self.tk_button_change_ping_window_size = self.__tk_button_change_ping_window_size(self.tk_tabs_tab_0)
        self.uart_rb, self.remote_rb = self.__tk_button_change_connection_type(self.tk_tabs_tab_0)

    def __win(self):
        self.title("Demo Controller")
        screenwidth = self.winfo_screenwidth()
        screenheight = self.winfo_screenheight()
        width = screenwidth
        height = screenheight
        geometry = '%dx%d+%d+%d' % (width, height, 0, 0)
        self.geometry(geometry)

        self.resizable(width=True, height=True)  # Allow window resizing


    def scrollbar_autohide(self,vbar, hbar, widget):
        """自动隐藏滚动条"""
        def show():
            if vbar: vbar.lift(widget)
            if hbar: hbar.lift(widget)
        def hide():
            if vbar: vbar.lower(widget)
            if hbar: hbar.lower(widget)
        hide()
        widget.bind("<Enter>", lambda e: show())
        if vbar: vbar.bind("<Enter>", lambda e: show())
        if vbar: vbar.bind("<Leave>", lambda e: hide())
        if hbar: hbar.bind("<Enter>", lambda e: show())
        if hbar: hbar.bind("<Leave>", lambda e: hide())
        widget.bind("<Leave>", lambda e: hide())

    def v_scrollbar(self,vbar, widget, x, y, w, h, pw, ph):
        widget.configure(yscrollcommand=vbar.set)
        vbar.config(command=widget.yview)
        vbar.place(relx=(w + x) / pw, rely=y / ph, relheight=h / ph, anchor='ne')

    def h_scrollbar(self,hbar, widget, x, y, w, h, pw, ph):
        widget.configure(xscrollcommand=hbar.set)
        hbar.config(command=widget.xview)
        hbar.place(relx=x / pw, rely=(y + h) / ph, relwidth=w / pw, anchor='sw')

    def create_bar(self,master, widget,is_vbar,is_hbar, x, y, w, h, pw, ph):
        vbar, hbar = None, None
        if is_vbar:
            vbar = Scrollbar(master)
            self.v_scrollbar(vbar, widget, x, y, w, h, pw, ph)
        if is_hbar:
            hbar = Scrollbar(master, orient="horizontal")
            self.h_scrollbar(hbar, widget, x, y, w, h, pw, ph)
        self.scrollbar_autohide(vbar, hbar, widget)

    def __tk_tabs_tab(self,parent):
        frame = Notebook(parent)
        self.tk_tabs_tab_0 = self.__tk_frame_tab_0(frame)
        frame.add(self.tk_tabs_tab_0, text="control")
        self.tk_tabs_tab_1 = self.__tk_frame_tab_1(frame)
        frame.add(self.tk_tabs_tab_1, text="info")
        self.ota_tab = OTAUpgradeTab(frame)
        frame.add(self.ota_tab, text="OTA Upgrade")
        frame.place(x=0, y=0, width=self.winfo_screenwidth(), height=self.winfo_screenheight())
        return frame

    def __tk_frame_tab_0(self,parent):
        frame = Frame(parent)
        frame.place(x=0, y=0, width=self.winfo_screenwidth(), height=self.winfo_screenheight())
        return frame

    def __tk_frame_tab_1(self,parent):
        frame = Frame(parent)
        frame.place(x=0, y=0, width=self.winfo_screenwidth(), height=self.winfo_screenheight())
        return frame

    def draw_lines_in_grid(self, canvas):
        for component_id in self.all_grid_components:
            canvas.delete(component_id)
        self.all_grid_components = []
        item_ids = canvas.find_all()
        for i in range(self.cols):
            for j in range(self.rows):
                x0, y0 = i * self.cell_width, j * self.cell_height
                x1, y1 = x0 + self.cell_width, y0 + self.cell_height
                self.all_grid_components.append(canvas.create_rectangle(x0, y0, x1, y1, outline="light grey"))

        for i in range(self.cols):
            j = 0
            x0, y0 = i * self.cell_width, j * self.cell_height
            x1, y1 = i * self.cell_width, self.rows * self.cell_height
            if i % 10 == 0:  # Add thicker lines every ten cells
                self.all_grid_components.append(canvas.create_line(x0, y0, x1, y1, width=1, fill="#C0C0C0"))

        for j in range(self.rows):
            i = 0
            x0, y0 = i * self.cell_width, j * self.cell_height
            x1, y1 = self.cell_width * self.cols, y0
            if j % 10 == 0:  # Add thicker lines every ten cells
                self.all_grid_components.append(canvas.create_line(x0, y0, x1, y1, width=1, fill="#C0C0C0"))
        for item in item_ids:
            canvas.tag_raise(item)

    def __tk_canvas_node_grid(self,parent):
        canvas = Canvas(parent,bg="#e0e0e0", highlightthickness=1, highlightbackground="black")
        canvas.place(x=0, y=0, width=self.grid_width, height=self.grid_height)
        self.draw_lines_in_grid(canvas)
        return canvas

    def __tk_canvas_rssi_table(self,parent):
        canvas = Canvas(parent,bg="white", highlightthickness=1, highlightbackground="black")
        canvas.place(x=0, y=0, width=500, height=500)
        # Draw table lines
        self.max_node_count = 20
        grid_size = self.grid_height/self.max_node_count
        for i in range(1, self.max_node_count):
            canvas.create_line(0, grid_size * i, self.grid_height, grid_size * i, fill="black")
            canvas.create_line(grid_size * i, 0, grid_size * i, self.grid_height, fill="black")
        return canvas

    def __tk_text_output(self, parent):
        frame = Frame(parent)
        frame.place(x=self.grid_width + 10, y=0, width=480, height=400)

        text = Text(frame)
        text.grid(row=0, column=0, sticky='nsew')

        scrollbar = Scrollbar(frame, command=text.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')

        text.config(yscrollcommand=scrollbar.set)

        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        return text, scrollbar, frame

    def __tk_input_cmd_input(self,parent):
        ipt = Entry(parent, )
        ipt.place(x=self.grid_width + 10, y=406, width=465, height=30)
        return ipt

    def get_local_ips(self):
        import socket
        hostname = socket.gethostname()
        local_ips = []
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for info in addr_info:
                ip = info[4][0]
                if ip.startswith('192.168') and ip not in local_ips:
                    local_ips.append(ip)
        except socket.gaierror:
            print("Error getting the IP address")
        return local_ips

    def __tk_list_box_cmd_list(self,parent):
        lb = Listbox(parent)

        lb.insert(END, "AT+WLDBG=wtn wtn_en")
        lb.insert(END, "AT+WLDBG=wtn wink_en")
        lb.insert(END, "AT+WLSTATE")
        lb.insert(END, "AT+WLDISCONN")
        lb.insert(END, f"AT+WLCONN=ssid,{wtn_config.ssid},pw,{wtn_config.password}")
        local_ips = self.get_local_ips()
        if local_ips:
            for local_ip in local_ips:
                lb.insert(END, f"AT+IPERF=-c,{local_ip},-i,1,-t,10,-b,20m,-u,-p,5006")
        else:
            lb.insert(END, "AT+IPERF=-c,192.168.0.103,-i,1,-t,10,-b,20m,-u,-p,5006")
            print("No local IP address starting with '192.168' found.")

        lb.insert(END, "AT+IPERF3=-s,-p,5006")
        lb.insert(END, "AT+IPERF=-s,-u,-p,5006,-i,1")
        lb.insert(END, f"{wtn_config.cmd_prefix} get_info")
        lb.insert(END, f"{wtn_config.cmd_prefix} b_wtn_dbg_power_save")
        lb.insert(END, f"{wtn_config.cmd_prefix} b_wtn_dbg_helpierx")
        lb.insert(END, f"{wtn_config.cmd_prefix} b_wtn_dbg_helpietx")
        lb.insert(END, f"{wtn_config.cmd_prefix} b_wtn_dbg_bcn_sync")

        lb.place(x=self.grid_width + 10, y=443, width=465, height=275)
        return lb

    def __tk_label_node_label(self,parent):
        label = Label(parent,text="select node first",anchor="center", )
        label.place(x=self.button_x, y=self.config_input_y, width=100, height=30)
        return label

    def __tk_button_mesh_enable_node(self, parent):
        btn = Button(parent, text="mesh enable", takefocus=False,)
        btn.place(x=self.button_x, y=self.button_y - 120, width=100, height=30)
        return btn


    def __tk_button_reset_node(self, parent):
        btn = Button(parent, text="node reset", takefocus=False,)
        btn.place(x=self.button_x, y=self.button_y - 80, width=100, height=30)
        return btn

    def __tk_button_ping(self, parent):
        btn = Button(parent, text="ping start", takefocus=False, )
        btn.place(x=self.button_x, y=self.button_y - 170, width=100, height=30)
        return btn

    def __tk_button_stop_ping(self, parent):
        btn = Button(parent, text="ping stop", takefocus=False, )
        btn.place(x=self.button_x, y=self.button_y - 210, width=100, height=30)
        return btn

    def __tk_button_reset_ping_results(self, parent):
        btn = Button(parent, text="ping reset", takefocus=False, )
        btn.place(x=self.button_x, y=self.button_y - 250, width=100, height=30)
        return btn

    def __tk_button_auto_move(self,parent):
        btn = Button(parent, text="move start", takefocus=False,)
        btn.place(x=self.button_x, y=self.button_y - 310, width=100, height=30)
        return btn

    def __tk_button_stop_move(self,parent):
        btn = Button(parent, text="move stop", takefocus=False,)
        btn.place(x=self.button_x, y=self.button_y - 350, width=100, height=30)
        return btn

    def __tk_button_stop_all(self,parent):
        btn = Button(parent, text="move stop all", takefocus=False,)
        btn.place(x=self.button_x, y=self.button_y - 390, width=100, height=30)
        return btn

    #def __tk_button_add_wall(self,parent):
    #    btn = Button(parent, text="wall add", takefocus=False,)
    #    btn.place(x=self.button_x, y=self.button_y - 410, width=100, height=30)
    #    return btn
    #def __tk_button_remove_wall(self,parent):
    #    btn = Button(parent, text="wall del", takefocus=False,)
    #    btn.place(x=self.button_x, y=self.button_y - 450, width=100, height=30)
    #    return btn


    def __tk_button_toggle_panel(self,parent):
        btn = Button(parent, text=">>", takefocus=False,)
        btn.place(x=self.button_x, y=80, width=100, height=30)
        return btn


    def __tk_highlight_node_mac_input(self,parent):
        ipt = EntryWithPlaceholder(parent, "MAC Address", )
        ipt.place(x=self.button_x, y=0, width=100, height=30)
        return ipt

    def __tk_button_power_save(self,parent):
        btn = Button(parent, text="power save", takefocus=False,)
        btn.place(x=self.button_x, y=40, width=100, height=30)
        return btn

    def __tk_label_dis_label(self,parent):
        label = Label(parent,text=f"The distance of each grid is set to {wtn_config.distance_per_grid} m.",anchor="center", )
        label.place(x=20, y=self.config_input_y, width=250, height=30)
        return label

    def __tk_input_dis_input(self,parent):
        ipt = Entry(parent, )
        ipt.place(x=270, y=self.config_input_y, width=35, height=30)
        return ipt

    def __tk_button_change_dis(self,parent):
        btn = Button(parent, text="change distance", takefocus=False,)
        btn.place(x=310, y=self.config_input_y, width=110, height=30)
        return btn

    def __tk_label_ping_window_size_label(self, parent):
        label = Label(parent,text=f"Ping rtt average window: {wtn_config.ping_rtt_aver_window_size} .",anchor="center", )
        label.place(x=430, y=self.config_input_y, width=150, height=30)
        return label

    def __tk_input_ping_window_size_input(self, parent):
        ipt = Entry(parent, )
        ipt.place(x=580, y=self.config_input_y, width=35, height=30)
        return ipt

    def __tk_button_change_ping_window_size(self,parent):
        btn = Button(parent, text="Apply", takefocus=False,)
        btn.place(x=620, y=self.config_input_y, width=50, height=30)
        return btn

    def __tk_checkbox_auto_layout(self, parent):
        self.checkbox_auto_layout_value = IntVar(value=1)
        checkbox = Checkbutton(parent, text="Auto layout",
                                  variable=self.checkbox_auto_layout_value)
        checkbox.place(x=1200, y=self.config_input_y-15, width=150, height=30)
        return checkbox

    def __tk_checkbox_show_info_embedded(self, parent):
        self.checkbox_show_info_embedded = IntVar(value=1)
        checkbox = Checkbutton(parent, text="Show info",
                                  variable=self.checkbox_show_info_embedded)
        checkbox.place(x=1200, y=self.config_input_y+10, width=150, height=30)
        return checkbox

    def __tk_label_ping_interval_label(self, parent):
        label = Label(parent,text=f"Ping Interval: {wtn_config.ping_interval} ms.",anchor="center", )
        label.place(x=680, y=self.config_input_y, width=150, height=30)
        return label

    def __tk_input_ping_interval_input(self, parent):
        ipt = Entry(parent, )
        ipt.place(x=830, y=self.config_input_y, width=35, height=30)
        return ipt

    def __tk_button_change_ping_interval(self,parent):
        btn = Button(parent, text="Apply", takefocus=False,)
        btn.place(x=870, y=self.config_input_y, width=50, height=30)
        return btn

    def __tk_button_change_connection_type(self, parent):
        connection_type_frame = ttk.Frame(parent, padding="10")
        connection_type_frame.place(x=930, y=self.config_input_y, width=200, height=50)

        self.connection_type = StringVar(value=wtn_config.Node_Mode.name)
        uart_rb = ttk.Radiobutton(connection_type_frame, text="UART", variable=self.connection_type, value="UART")
        remote_rb = ttk.Radiobutton(connection_type_frame, text="SOCKET", variable=self.connection_type, value="SOCKET")

        uart_rb.pack(side=LEFT, padx=10, pady=5)
        remote_rb.pack(side=LEFT, padx=10, pady=5)

        return uart_rb, remote_rb

class Win(WinGUI):
    def __init__(self, controller):
        self.ctl = controller
        super().__init__()
        self.__event_bind()
        self.__style_config()
        self.ctl.init(self)
        self.ota_tab.controller = self.ctl
        self.ota_tab.ifname = controller.chosen_iface

    def __event_bind(self):
        self.tk_canvas_node_grid.bind('<Button-1>',self.ctl.select_node)
        self.tk_canvas_node_grid.bind("<B1-Motion>", self.ctl.drag_node)
        self.tk_canvas_node_grid.bind("<ButtonRelease-1>", self.ctl.generate_rssi_table)
        self.tk_list_box_cmd_list.bind('<<ListboxSelect>>',self.ctl.select_cmd)
        self.tk_list_box_cmd_list.bind('<Double-Button-1>',self.ctl.double_select_cmd)
        self.tk_input_cmd_input.bind('<Return>',self.ctl.input_cmd)
        self.tk_button_ping.bind('<Button-1>', self.ctl.ping_select)
        self.tk_button_reset_ping_results.bind('<Button-1>', self.ctl.reset_ping_results)
        self.tk_button_stop_ping.bind('<Button-1>', self.ctl.stop_ping_select)
        self.tk_button_change_ping_interval.bind('<Button-1>', self.ctl.change_ping_interval)
        self.tk_button_toggle_panel.bind('<Button-1>', self.toggle)
        self.tk_button_power_save.bind('<Button-1>',self.ctl.power_save)
        #self.tk_button_add_wall.bind('<Button-1>', self.ctl.add_wall)
        #self.tk_button_remove_wall.bind('<Button-1>', self.ctl.remove_wall)
        self.uart_rb.bind('<Button-1>', self.ctl.set_connection_to_uart)
        self.remote_rb.bind('<Button-1>', self.ctl.set_connection_to_remote)
        self.tk_checkbox_auto_layout.configure(command=self.auto_layout_toggle)
        self.tk_checkbox_show_info_embedded.configure(command=self.info_embedded_toggle)
        self.tk_highlight_node_mac_input.bind('<KeyRelease>', self.highlight_node_mac_changed)
        if not wtn_config.Node_Mode == ConnectionType.SOCKET:
            self.tk_button_mesh_enable_node.bind('<Button-1>', self.ctl.mesh_enable)
            self.tk_button_reset_node.bind('<Button-1>', self.ctl.reset_node)
            self.tk_button_auto_move.bind('<Button-1>', self.ctl.auto_move_select)
            self.tk_button_stop_move.bind('<Button-1>', self.ctl.stop_move_select)
            self.tk_button_stop_all.bind('<Button-1>', self.ctl.stop_move_all)
            self.tk_button_change_ping_window_size.bind('<Button-1>', self.ctl.change_ping_window_size)
            self.tk_button_change_dis.bind('<Button-1>', self.ctl.change_distance)
        self.toggle(None)

    def __style_config(self):
        pass

    def auto_layout_toggle(self):
        logging.debug("Auto layout toggle")
        self.ctl.auto_layout_toggle(self.checkbox_auto_layout_value.get() == 1)

    def info_embedded_toggle(self):
        logging.debug("Info embedded toggle")
        self.ctl.info_embedded_toggle(self.checkbox_show_info_embedded.get() == 1)

    def highlight_node_mac_changed(self, evt):
        logging.debug("Highlight node mac changed")
        self.ctl.on_highlight_node_mac_changed(self.tk_highlight_node_mac_input.get().replace(":","").lower())

    def toggle(self, evt):
        self.show_panel = not self.show_panel
        if self.show_panel:
            self.grid_width = self.winfo_screenwidth() - 620
            self.text_frame.place(x=self.grid_width + 10, y=0, width=480, height=400)
            self.tk_input_cmd_input.place(x=self.grid_width + 10, y=406, width=465, height=30)
            self.tk_list_box_cmd_list.place(x=self.grid_width + 10, y=443, width=465, height=275)
            self.tk_button_toggle_panel.config(text=">>")
        else:
            self.grid_width = self.winfo_screenwidth() - 130
            self.text_frame.place_forget()
            self.tk_input_cmd_input.place_forget()
            self.tk_list_box_cmd_list.place_forget()
            self.tk_button_toggle_panel.config(text="<<")
        self.rows = self.grid_height // self.grid_size
        self.cols = self.grid_width // self.grid_size
        self.tk_canvas_node_grid.place(x=0, y=0, width=self.grid_width, height=self.grid_height)
        self.draw_lines_in_grid(self.tk_canvas_node_grid)

if __name__ == "__main__":
    win = WinGUI()
    win.mainloop()
