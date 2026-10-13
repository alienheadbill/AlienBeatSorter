import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for worker processes on Windows
    try:
        from beatsorter.gui import run
    except Exception as e:  # broken install: say so instead of closing silently
        import traceback
        msg = ("Beat Sorter couldn't start because some of its files are missing or "
               f"damaged ({e}).\n\nTo repair it, download the latest version from\n"
               "https://github.com/alienheadbill/AlienBeatSorter\n(Code > Download ZIP) "
               "and copy its files over your Beat Sorter folder.\n"
               "Your beats, tags and settings are not affected.")
        print(traceback.format_exc(), file=sys.stderr)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "Beat Sorter", 0x10)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)
    run()
