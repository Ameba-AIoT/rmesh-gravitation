import ctypes
import logging
import platform
from tkinter import PhotoImage

from interface_selector import launch_interface_selection
from utils import resource_path
from wtn_control import Controller as MainUIController
from wtn_ui import Win as MainWin


def configure_logging():
    from wtn_config import logging_enabled
    if logging_enabled:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.basicConfig(level=logging.CRITICAL)  # Only log critical errors


if __name__ == "__main__":
    # Ask user to choose a network interface
    chosen_iface = launch_interface_selection()
    configure_logging()

    logging.info(f"Chosen interface: {chosen_iface}")
    app = MainWin(MainUIController(chosen_iface))
    app.title("Gravitation")
    icon_path = resource_path("black-hole.png")
    icon_image = PhotoImage(file=icon_path)
    app.iconphoto(True, icon_image)
    if platform.system() == "Windows":
        # Set an unique id for this app
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Gravitation")
    logging.info("Starting main loop")
    app.mainloop()
