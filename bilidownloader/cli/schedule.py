import re
from enum import Enum
from typing import Annotated, Optional

import typer
from rich import box
from rich import print as rprint
from rich.console import Console
from rich.table import Column, Table

from bilidownloader.apis.api import BiliApi
from bilidownloader.cli.application import app
from bilidownloader.cli.options import SHOWURL_OPT
from bilidownloader.commons.alias import SERIES_ALIASES

console = Console()


class DayOfWeek(str, Enum):
    TODAY = "today"
    NOW = "now"
    MONDAY = "monday"
    MON = "mon"
    MO = "mo"
    TUESDAY = "tuesday"
    TUE = "tue"
    TU = "tu"
    WEDNESDAY = "wednesday"
    WED = "wed"
    WE = "we"
    THURSDAY = "thursday"
    THU = "thu"
    TH = "th"
    FRIDAY = "friday"
    FRI = "fri"
    FR = "fr"
    SATURDAY = "saturday"
    SAT = "sat"
    SA = "sa"
    SUNDAY = "sunday"
    SUN = "sun"
    SU = "su"


@app.command(
    "schedule",
    help="View the release schedule. Alias: calendar, cal, sch, timetable, tt",
)
@app.command("calendar", help="View the release schedule", hidden=True)
@app.command("cal", help="View the release schedule", hidden=True)
@app.command("sch", help="View the release schedule", hidden=True)
@app.command("timetable", help="View the release schedule", hidden=True)
@app.command("tt", help="View the release schedule", hidden=True)
def schedule(
    show_url: SHOWURL_OPT = False,
    day: Annotated[
        Optional[DayOfWeek],
        typer.Option(
            "--day",
            "-d",
            help="Filter by a specific day",
            rich_help_panel="Filter",
            show_choices=False,
            show_default=False,
        ),
    ] = None,
) -> None:
    api = BiliApi()
    data = api.get_anime_timeline()
    tpat = re.compile(r"(\d{2}:\d{2})")
    epat = re.compile(r"E(\d+(-\d+)?)")
    rprint(
        "[reverse green] Note [/] [green]Episodes that have already aired will not display an airtime in the table."
    )
    # Map short names to full day names
    short_to_full = {
        DayOfWeek.MON: DayOfWeek.MONDAY,
        DayOfWeek.MO: DayOfWeek.MONDAY,
        DayOfWeek.TUE: DayOfWeek.TUESDAY,
        DayOfWeek.TU: DayOfWeek.TUESDAY,
        DayOfWeek.WED: DayOfWeek.WEDNESDAY,
        DayOfWeek.WE: DayOfWeek.WEDNESDAY,
        DayOfWeek.THU: DayOfWeek.THURSDAY,
        DayOfWeek.TH: DayOfWeek.THURSDAY,
        DayOfWeek.FRI: DayOfWeek.FRIDAY,
        DayOfWeek.FR: DayOfWeek.FRIDAY,
        DayOfWeek.SAT: DayOfWeek.SATURDAY,
        DayOfWeek.SA: DayOfWeek.SATURDAY,
        DayOfWeek.SUN: DayOfWeek.SUNDAY,
        DayOfWeek.SU: DayOfWeek.SUNDAY,
        DayOfWeek.NOW: DayOfWeek.TODAY,
    }
    if day:
        day = short_to_full.get(day, day)
    for dow in data.data.items:
        if dow.is_today and day == DayOfWeek.TODAY:
            day = DayOfWeek(dow.full_day_of_week.lower())
        if day is not None and str(day.name.lower()) != dow.full_day_of_week.lower():
            continue
        is_today = " [blue] >> TODAY << [/]" if dow.is_today else ""
        rprint(
            f"[reverse blue bold] {dow.full_day_of_week} [/][reverse white] {dow.full_date_text} [/]{is_today}"
        )
        tab = Table(
            Column("Time", justify="center"),
            "Series ID",
            "Title",
            "Ep.",
            box=box.ROUNDED,
        )
        if show_url:
            tab.add_column("URL")
        released = []
        upcoming = []
        if not dow.cards:
            console.print(tab)
            continue
        for item in dow.cards:
            tmat = tpat.search(item.index_show)
            time = tmat.group(0) if tmat else ""
            emat = epat.search(item.index_show)
            eps = emat.group(0) if emat else ""
            title = (
                SERIES_ALIASES[item.season_id]
                if item.season_id in SERIES_ALIASES
                else item.title
            )
            ent = [time, item.season_id, title, eps]
            if show_url:
                ent.append(
                    f"https://www.bilibili.tv/play/{item.season_id}/{item.episode_id}"
                )
            released.append(ent) if time == "" else upcoming.append(ent)
        released = sorted(released, key=lambda e: e[2])
        upcoming = sorted(upcoming, key=lambda e: e[0])
        released.extend(upcoming)
        for anime in released:
            tab.add_row(*anime)
        console.print(tab)
