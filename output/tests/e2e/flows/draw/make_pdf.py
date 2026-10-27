"""生成测试图纸：二楼水电点位图 V1 / V2 / V3（Pillow 绘制后存为 PDF）。"""
from PIL import Image, ImageDraw, ImageFont
import os
import sys
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
F = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
S = 2  # 800x520 布局放大 2 倍

def draw(version):
    W, H = 800 * S, 560 * S
    im = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(im)
    f_room = ImageFont.truetype(F, 22 * S)
    f_dim = ImageFont.truetype(F, 14 * S)
    f_title = ImageFont.truetype(F, 18 * S)
    k = lambda *a: [x * S for x in a]
    g.rectangle(k(40, 40, 760, 480), outline="#374151", width=6 * S)
    for x0, y0, x1, y1 in [(150,40,150,240),(380,40,380,240),(460,40,460,240),(640,40,640,240),(40,240,760,240),
                           (40,300,760,300),(160,300,160,480),(400,300,400,480),(580,300,580,480)]:
        g.line(k(x0, y0, x1, y1), fill="#374151", width=3 * S)
    for x0, x1, y in [(620,690,300),(440,500,300),(240,310,300),(230,290,240),(520,580,240),(80,130,300)]:
        g.line(k(x0, y, x1, y), fill="white", width=8 * S)
    g.arc(k(550, 230, 690, 370), 270, 360, fill="#5b6779", width=S)
    g.line(k(620, 300, 620, 370), fill="#5b6779", width=S)
    g.text(k(655, 284), "门洞 900", font=f_dim, fill="#5b6779", anchor="mm")
    for name, x, y in [("主卫",95,150),("主卧",265,150),("衣帽间",420,150),("次卧",550,150),("次卫",700,150),("走廊",400,270),
                       ("楼梯间",100,400),("家庭厅",280,400),("书房 A",490,400),("书房 B",670,420)]:
        g.text(k(x, y), name, font=f_room, fill="#5b6779", anchor="mm")
    # 线管（虚线）
    pipe = [(100,150),(100,228),(690,228),(690,150)] if version < 3 else [(100,70),(200,70),(200,40)]
    for (x0,y0),(x1,y1) in zip(pipe, pipe[1:]):
        steps = int(max(abs(x1-x0), abs(y1-y0)) / 10) or 1
        for i in range(0, steps, 2):
            a = (x0 + (x1-x0)*i/steps, y0 + (y1-y0)*i/steps); b = (x0 + (x1-x0)*(i+1)/steps, y0 + (y1-y0)*(i+1)/steps)
            g.line(k(*a, *b), fill="#5b6779", width=2 * S)
    g.line(k(752, 330, 752, 460, 700, 460), fill="#5b6779", width=S)
    socks = [(196,44),(300,44),(590,44),(300,472),(470,472)]
    if version >= 2:
        socks += [(690,472),(716,472)]  # 书房 B 南墙新增 2 个五孔插座（BG-001）
    for x, y in socks:
        g.rectangle(k(x, y, x + 14, y + 8), outline="#374151", width=2 * S, fill="white")
    g.text(k(40, 520), f"君华新城 · 联排别墅  二楼水电点位图  V{version}", font=f_title, fill="#111827")
    return im

for v in (1, 2, 3):
    draw(v).save(os.path.join(OUT, f"二楼水电点位图-V{v}.pdf"), "PDF", resolution=150)
    print("ok", v)
