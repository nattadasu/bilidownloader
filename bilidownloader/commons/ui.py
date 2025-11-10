from pathlib import Path
from typing import Optional

from notifypy import Notify
from survey import printers

ins_notify = Notify()


def prn_info(message: str) -> None:
    """
    Prints an informational message to the console.

    Args:
        message (str): the informational message

    Returns:
        None

    Note:
        If the program is running headless, the message will be printed
        using the built-in print function as a fallback. The default behavior
        may raises fatal error if the program is running on a headless
        environment.
    """
    try:
        printers.info(message)
    except Exception as _:
        print(f"!> {message}")


def prn_done(message: str) -> None:
    """
    Prints a success message to the console.

    Args:
        message (str): the success message

    Returns:
        None

    Note:
        If the program is running headless, the message will be printed
        using the built-in print function as a fallback. The default behavior
        may raises fatal error if the program is running on a headless
    """
    try:
        printers.done(message)
    except Exception as _:
        print(f"O> {message}")


def prn_error(message: str) -> None:
    """
    Prints an error message to the console.

    Args:
        message (str): the error message

    Returns:
        None

    Note:
        If the program is running headless, the message will be printed
        using the built-in print function as a fallback. The default behavior
        may raises fatal error if the program is running on a headless
        environment.
    """
    try:
        printers.fail(message)
    except Exception as _:
        print(f"X> {message}")


def push_notification(title: str, index: str, path: Optional[Path] = None) -> None:
    """
    Send native notification for Windows, Linux, and macOS, exclusively used
    for episode download.

    Args:
        title (str): the title of the episode
        index (str): the episode index
        path (Optional[Path], optional): the path to the downloaded file

    Returns:
        None
    """
    ins_notify.application_name = "BiliDownloader"
    if path:
        ins_notify.title = f"{title}, {index} downloaded"
        ins_notify.message = f"File is saved on {path.resolve()}"
    else:
        ins_notify.title = f"Downloading {title}, {index}"
        ins_notify.message = "We will notify you when it's done"
    try:
        ins_notify.send(block=False)
    except Exception as _:
        ...
