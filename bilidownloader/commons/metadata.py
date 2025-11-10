import importlib.metadata as mdata

__VERSION__ = mdata.version("bilidownloader")
__VERSION_INFO__ = tuple(map(int, __VERSION__.split(".")))
__DESCRIPTION__ = mdata.metadata("bilidownloader")["Summary"]
