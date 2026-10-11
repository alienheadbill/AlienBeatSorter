import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for worker processes on Windows
    from beatsorter.gui import run

    run()
