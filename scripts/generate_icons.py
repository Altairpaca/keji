"""生成 PWA 应用图标（规格 §4，ADR-014）。

设计：品牌蓝（#1d4ed8）圆角方块底色 + 白色「客」字（Noto Sans CJK）。
无中文字体时回退为几何图形（圆 + 弧线），不依赖字体。

用法：python scripts/generate_icons.py
输出：static/icons/{icon-192,icon-512,apple-touch-icon-180,favicon-32}.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND = "#1d4ed8"
WHITE = "#ffffff"
CHAR = "客"

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"

# 文件名 → 边长（px）。apple-touch-icon 满幅底色（iOS 自行圆角），其余圆角方块。
ICON_SIZES: dict[str, tuple[int, bool]] = {
    "icon-192.png": (192, False),
    "icon-512.png": (512, False),
    "apple-touch-icon-180.png": (180, True),
    "favicon-32.png": (32, False),
}

# 常见中文字体候选（按优先级）。.ttc 为字体集合，逐索引探测 SC 族。
FONT_CANDIDATES: list[tuple[str, str]] = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "SC"),
    ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "SC"),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", ""),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", ""),
]


def load_cjk_font(pixel_size: int) -> ImageFont.FreeTypeFont | None:
    """加载中文字体；找不到返回 None（调用方回退几何图形）。"""
    fallback: ImageFont.FreeTypeFont | None = None
    for path, preferred in FONT_CANDIDATES:
        if not Path(path).is_file():
            continue
        for index in range(8):  # ttc 内逐索引探测
            try:
                font = ImageFont.truetype(path, pixel_size, index=index)
            except (OSError, ValueError):
                break
            family = "".join(font.getname()).upper()
            if preferred and preferred in family:
                return font
            if fallback is None:
                fallback = font
    return fallback


def _draw_geo_fallback(draw: ImageDraw.ImageDraw, size: int) -> None:
    """几何图形 logo：白圆 + 断弧（无中文字体时的兜底）。"""
    center = size * 0.5
    r = size * 0.21
    box = (center - r, center - r, center + r, center + r)
    draw.ellipse(box, fill=WHITE)
    arc_r = size * 0.32
    draw.arc(
        (center - arc_r, center - arc_r, center + arc_r, center + arc_r),
        start=140,
        end=320,
        fill=WHITE,
        width=max(2, round(size * 0.05)),
    )


def draw_icon(size: int, full_bleed: bool, font: ImageFont.FreeTypeFont | None) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if full_bleed:
        draw.rectangle([0, 0, size - 1, size - 1], fill=BRAND)
    else:
        radius = round(size * 0.22)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BRAND)

    if font is None:
        _draw_geo_fallback(draw, size)
        return img

    char_font = font.font_variant(size=round(size * 0.55))
    bbox = draw.textbbox((0, 0), CHAR, font=char_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) / 2 - bbox[0]
    y = (size - text_h) / 2 - bbox[1]
    draw.text((x, y), CHAR, font=char_font, fill=WHITE)
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font = load_cjk_font(round(512 * 0.55))
    if font is None:
        print("未找到中文字体，使用几何图形 logo。")
    else:
        print(f"中文字体：{'/'.join(font.getname())}")

    for name, (size, full_bleed) in ICON_SIZES.items():
        icon = draw_icon(size, full_bleed, font)
        path = OUT_DIR / name
        icon.save(path, format="PNG")
        print(f"生成 {path}（{size}x{size}）")


if __name__ == "__main__":
    main()
