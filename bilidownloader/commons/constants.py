from enum import Enum
from pathlib import Path

import platformdirs

WEB_API_URL = "https://api.bilibili.tv/intl/gateway/web/v2"
BASE_DIR = Path(platformdirs.user_data_dir("bilidownloader"))
DEFAULT_COOKIES = BASE_DIR / "cookies.txt"
DEFAULT_HISTORY = BASE_DIR / "history.v2.tsv"
DEFAULT_WATCHLIST = BASE_DIR / "watchlist.txt"
REINSTALL_ARGS = 'pipx install "bilidownloader[ass] @ git+https://github.com/nattadasu/bilidownloader.git"'


class VideoResolution(str, Enum):
    """Available resolutions on Bstation, 4K was skipped"""

    P144 = "144"
    P240 = "240"
    P360 = "360"
    P480 = "480"
    P720 = "720"
    P1080 = "1080"
    P2160 = "2160"
