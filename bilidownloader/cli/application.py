from typer_di import TyperDI

from bilidownloader.commons.metadata import __DESCRIPTION__, __VERSION__

app = TyperDI(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
    help=f"{__DESCRIPTION__} (Version: {__VERSION__})",
)

hi_app = TyperDI(pretty_exceptions_show_locals=False, no_args_is_help=True)
wl_app = TyperDI(pretty_exceptions_show_locals=False, no_args_is_help=True)
