from http.cookiejar import MozillaCookieJar as MozCookie
from pathlib import Path
from typing import List, Optional, Tuple, Union

import requests as req

from bilidownloader.api_model import BiliTvResponse, CardItem
from bilidownloader.common import API_URL


class BiliApi:
    def __init__(self, api_url: str = API_URL):
        self.api_url = api_url
        self.data = self._get_api_resp()

    def _get_api_resp(self) -> BiliTvResponse:
        """Get API response from Bilibili and convert to Data Object

        Returns:
            BiliTvResponse: Response in Model Object
        """
        resp = req.get(self.api_url)
        resp.raise_for_status()
        return BiliTvResponse(**resp.json())

    def get_today_schedule(self) -> List[CardItem]:
        return [
            card for day in self.data.data.items if day.is_today for card in day.cards
        ]

    def get_all_shows(self) -> List[CardItem]:
        return [
            card
            for day in self.data.data.items
            for card in day.cards
            if card.is_available
        ]

    def get_all_shows_simple(self) -> List[Tuple[str, str]]:
        anime = {}

        for day in self.data.data.items:
            for card in day.cards:
                # Use a dictionary to remove duplicates by season_id
                anime[str(card.season_id)] = card.title

        # Convert dictionary to a list of tuples and sort by title
        sorted_anime = sorted(anime.items(), key=lambda x: x[1])

        return sorted_anime


class BiliHtml:
    def __init__(
        self,
        cookie_path: Union[str, Path, None] = None,
        user_agent: Optional[str] = None,
    ):
        self.cookie = cookie_path
        self.user_agent = (
            user_agent
            or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )

    def get(self, url: str) -> req.Response:
        """Get an object"""

        sess = req.Session()
        if self.cookie:
            jar = MozCookie(self.cookie)
            jar.load()
            sess.cookies.update(jar)

        resp = sess.get(url, headers={"User-Agent": self.user_agent})
        resp.raise_for_status()
        return resp
