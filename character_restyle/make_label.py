"""Regenerate label_bitch.png, the lettering strip wrapped around the black bandeau.

    python make_label.py [path/to/japanese-font.ttf]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
W, H = 2048, 560   # one tile; restyle.py keeps this aspect ratio on the garment
img = Image.new("RGB", (W, H), (5, 6, 9))
draw = ImageDraw.Draw(img)
font = ImageFont.truetype(FONT, 300)
text = "ビッチ"
box = draw.textbbox((0, 0), text, font=font, stroke_width=9)
x = (W - (box[2] - box[0])) // 2 - box[0]
y = (H - (box[3] - box[1])) // 2 - box[1]
draw.text((x, y), text, font=font, fill=(240, 240, 240), stroke_width=9, stroke_fill=(240, 240, 240))
img.save(Path(__file__).with_name("label_bitch.png"))
