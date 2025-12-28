from http.cookiejar import MozillaCookieJar as MozCookie
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

import requests as req

from bilidownloader.apis.models import (
    BiliFavoriteResponse,
    BiliFavoritesListResponse,
    BiliTvResponse,
    CardItem,
)
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import WEB_API_URL


class BiliApi:
    def __init__(
        self,
        api_url: str = WEB_API_URL,
        cookie_path: Union[str, Path, None] = None,
        proxy: Optional[str] = None,
    ):
        self.api_url = api_url
        self.unified_params = {
            "s_locale": "en_US",
            "platform": "web",
        }
        self.cookie = cookie_path
        self.session = req.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        if self.cookie:
            jar = MozCookie(self.cookie)
            jar.load()
            self.session.cookies.update(jar)

    def get_anime_timeline(self) -> BiliTvResponse:
        """Get API response from Bilibili and convert to Data Object

        Returns:
            BiliTvResponse: Response in Model Object
        """
        uri = f"{self.api_url}/anime/timeline"
        resp = self.session.get(uri, params=self.unified_params)
        resp.raise_for_status()
        return BiliTvResponse(**resp.json())

    def get_favorites(self, pn: int = 1, ps: int = 20) -> BiliFavoritesListResponse:
        """Get favorites list

        Args:
            pn (int, optional): Page number. Defaults to 1.
            ps (int, optional): Page size. Defaults to 20.

        Returns:
            BiliFavoritesListResponse: Response in Model Object
        """
        if not self.cookie:
            raise ValueError("Cookie path must be set to perform this action")

        uri = f"{self.api_url}/fav/list"
        params = self.unified_params.copy()
        params.update({
            "type": "2",
            "sub_type": "101",
            "pn": str(pn),
            "ps": str(ps),
        })
        resp = self.session.get(uri, params=params)
        resp.raise_for_status()
        return BiliFavoritesListResponse(**resp.json())

    def post_favorite(
        self, action: Literal["add", "del"], show_id: Union[int, str]
    ) -> BiliFavoriteResponse:
        """Add or remove a show from favorites

        Args:
            action (Literal["add", "del"]): Action to perform
            show_id (Union[int, str]): Show ID

        Returns:
            BiliFavoriteResponse: Response in Model Object
        """
        if not self.cookie:
            raise ValueError("Cookie path must be set to perform this action")

        spm_id = (
            "bstar-web.pgc-video-detail.0.0"
            if action == "add"
            else "bstar-web.mylist-video.0.0"
        )

        post_body = {
            "from_spm_id": spm_id,
            "rid": f"{show_id}",
            "type": 2,
        }
        uri = f"{self.api_url}/fav/{action}"
        resp = self.session.post(uri, json=post_body, params=self.unified_params)
        resp.raise_for_status()
        return BiliFavoriteResponse(**resp.json())

    def get_today_schedule(self) -> List[CardItem]:
        """
        Get today's schedule

        Returns:
            List[CardItem]: List of CardItem
        """
        data = self.get_anime_timeline()
        final: List[CardItem] = []
        for day in data.data.items:
            if day.is_today and day.cards:
                final.extend(day.cards)
        return final

    def get_all_available_shows(self) -> List[CardItem]:
        """
        Get all available shows

        Returns:
            List[CardItem]: List of CardItem
        """
        data = self.get_anime_timeline()
        final: List[CardItem] = []
        for day in data.data.items:
            if not day.cards:
                continue
            for card in day.cards:
                if not card.is_available:
                    continue
                final.append(card)
        return final

    def get_all_shows_simple(self) -> List[Tuple[str, str]]:
        """
        Get all available shows in a simple list

        Returns:
            List[Tuple[str, str]]: List of tuples with season_id and title
        """
        anime = {}
        data = self.get_anime_timeline()

        for day in data.data.items:
            if not day.cards:
                continue
            for card in day.cards:
                # Use a dictionary to remove duplicates by season_id
                season_id_str = str(card.season_id)
                title = card.title
                if season_id_str in SERIES_ALIASES:
                    title = SERIES_ALIASES[season_id_str]
                anime[season_id_str] = title

        # Convert dictionary to a list of tuples and sort by title
        sorted_anime = sorted(anime.items(), key=lambda x: x[1])

        return sorted_anime


class BiliHtml:
    def __init__(
        self,
        cookie_path: Union[str, Path, None] = None,
        user_agent: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        self.cookie = cookie_path
        self.user_agent = (
            user_agent
            or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        self.session = req.Session()
        self.session.headers["User-Agent"] = self.user_agent
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        if self.cookie:
            jar = MozCookie(self.cookie)
            jar.load()
            self.session.cookies.update(jar)

    def get(self, url: str) -> req.Response:
        """
        Get an object

        Args:
            url (str): URL to get

        Returns:
            req.Response: Response object
        """

        resp = self.session.get(url)
        resp.raise_for_status()
        return resp
