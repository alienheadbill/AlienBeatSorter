"""Beat Sorter."""

import os as _os


def _numba_cache_dir() -> None:
    """librosa compiles some functions (with numba) the first time they run
    and saves the result. Keep those files in Beat Sorter's data folder:
    always writable, and not inside the program files the updater replaces.
    Set before librosa loads, in the app and in every analysis worker."""
    if "NUMBA_CACHE_DIR" in _os.environ:
        return
    try:
        from .config import app_dir
        d = app_dir() / "numba_cache"
        d.mkdir(parents=True, exist_ok=True)
        _os.environ["NUMBA_CACHE_DIR"] = str(d)
    except Exception:
        pass


_numba_cache_dir()
