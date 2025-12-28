from datetime import date, datetime
from re import search as rsearch
from typing import List, Optional

from pydantic import BaseModel, HttpUrl


class CornerMark(BaseModel):
    text: str
    left_icon: str
    image: str
    bg_color: str


class ViewHistory(BaseModel):
    progress: int
    progress_text: str


class CardItem(BaseModel):
    type: str
    card_type: str
    title: str
    cover: HttpUrl
    view: str
    dm: str
    styles: str
    style_list: List[str]
    season_id: str
    episode_id: str
    index_show: str
    label: int
    rank_info: None
    view_history: Optional[ViewHistory] = None
    watched: str
    duration: str
    view_at: str
    pub_time_text: str
    pub_time_ts: int
    is_favored: bool
    unavailable: bool
    corner_mark: Optional[CornerMark] = None

    @property
    def is_available(self) -> bool:
        """
        Check if the episode is available to watch

        Returns:
            bool: Episode is available
        """
        return bool(rsearch(r"updated$", self.index_show))


class DayItem(BaseModel):
    day_of_week: str
    is_today: bool
    date_text: str
    full_date_text: date
    full_day_of_week: str
    # In some cases, especially at the final weeks of the season, the cards are
    # None
    cards: Optional[List[CardItem]] = None


class ReturnData(BaseModel):
    items: List[DayItem]
    current_time: str
    current_time_ts: datetime


class FavoriteData(BaseModel):
    has_more: bool
    cards: List[CardItem]


class BiliTvResponse(BaseModel):
    code: int
    message: str
    ttl: int
    data: ReturnData


class BiliFavoriteResponse(BaseModel):
    code: int
    message: str
    ttl: int


class BiliFavoritesListResponse(BaseModel):
    code: int
    message: str
    ttl: int
    data: FavoriteData
