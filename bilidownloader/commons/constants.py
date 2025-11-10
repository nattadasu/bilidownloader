from pathlib import Path
from typing import Literal, Union

import platformdirs

WEB_API_URL = "https://api.bilibili.tv/intl/gateway/web/v2"
BASE_DIR = Path(platformdirs.user_data_dir("bilidownloader"))
DEFAULT_COOKIES = BASE_DIR / "cookies.txt"
DEFAULT_HISTORY = BASE_DIR / "history.v2.tsv"
DEFAULT_WATCHLIST = BASE_DIR / "watchlist.txt"
REINSTALL_ARGS = 'pipx install "bilidownloader[ass] @ git+https://github.com/nattadasu/bilidownloader.git"'

available_res = Union[
    Literal[144],
    Literal[240],
    Literal[360],
    Literal[480],
    Literal[720],
    Literal[1080],
    Literal[2160],
]
"""Available resolutions on Bstation, 4K was skipped"""
