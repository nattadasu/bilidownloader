from json import dumps
from math import modf
from re import search
from typing import Any

from ass import parse_string as ass_loads
from yt_dlp.postprocessor import PostProcessor


class SSARescaler(PostProcessor):
    def run(self, info) -> tuple[list[Any], Any]:
        # Replace string from "Noto Sans,100" to "Noto Sans,65" on all
        # subtitle files
        def return_dump() -> tuple[list[Any], Any]:
            return [], info

        self.to_screen("Changing subtitle font size")
        fpath: dict[str, str] = info.get("__files_to_move", {})
        if len(fpath) == 0:
            self.report_error("No filepath found in the metadata")
            return return_dump()
        fonts: list[str] = []
        for _, sub_file in fpath.items():
            if not sub_file.endswith("ass"):
                self.report_warning(f"{sub_file} is skipped as it's not SSA file")
                continue
            try:
                with open(sub_file, "r", encoding="utf-8-sig") as file:
                    content = file.read()
                    ass = ass_loads(content)
            except ValueError:
                with open(sub_file, "r", encoding="utf-8") as file:
                    content = file.read()
                    ass = ass_loads(content)

            ass.fields["Title"] = "Modified with github:nattadasu/bilidownloader"
            size_mod = 0.75

            for style in ass.styles:
                if style.fontname not in fonts:
                    fonts.append(style.fontname)
                style.fontsize = style.fontsize * size_mod
                style.outline = style.outline * size_mod
                style.shadow = style.shadow * size_mod
                if '-' not in style.name:
                    style.margin_v = int(style.margin_v * 0.6)
                    style.margin_r = int(style.margin_l * 0.6)
                    style.margin_l = int(style.margin_r * 0.6)

            def valmod(value: str) -> int | float | str:
                try:
                    val = float(value) * size_mod
                    frac, _ = modf(val)
                    return int(val) if frac == 0.0 else val
                except ValueError:
                    return value

            for line in ass.events:
                if fs := search(r"\\fs([\d\.]+)", line.text):
                    line.text = line.text.replace(f"\\fs{fs}", f"\\fs{valmod(fs)})")
                if bord := search(r"\\bord([\d\.]+)", line.text):
                    line.text = line.text.replace(f"\\bord{bord}", f"\\bord{valmod(bord)}")
                if shad := search(r"\\shad([\d\.]+)", line.text):
                    line.text = line.text.replace(f"\\shad{shad_}", f"\\shad{valmod(shad)}")

            with open(sub_file, "w", encoding="utf-8-sig") as file:
                ass.dump_file(file)
            self.to_screen(f"{sub_file} has been properly formatted")

        if len(fonts) > 0:
            with open("fonts.json", "w", encoding="utf-8") as file:
                file.write(dumps(fonts))

        return return_dump()

