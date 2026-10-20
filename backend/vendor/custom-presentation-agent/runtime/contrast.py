"""Repair unreadable native copy against a proven flat source background."""
import re

def luminance(color):
    values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(a*b for a,b in zip(linear,(.2126,.7152,.0722)))

def ratio(a,b):
    x,y=sorted((luminance(a),luminance(b)))
    return (y+.05)/(x+.05)

def readable_color(current,background,palette):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',current or '') or ratio(current,background)>=2:return None
    candidates=[c for c in palette if re.fullmatch(r'#[0-9a-fA-F]{6}',c or '') and ratio(c,background)>=4.5]
    return max(candidates,key=lambda c:ratio(c,background)) if candidates else None
