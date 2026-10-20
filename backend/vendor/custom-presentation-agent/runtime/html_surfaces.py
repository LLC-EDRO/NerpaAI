"""Measured neutral source panels and busy-background readability evidence."""
from PIL import Image

def neutral_source_surfaces(image,width,height):
    small=image.convert('RGB').resize((160,max(24,round(160*height/width))),Image.Resampling.NEAREST)
    w,h=small.size;pixels=small.load();result=[]
    mask=[[min(pixels[x,y])>=230 and max(pixels[x,y])-min(pixels[x,y])<=10 for x in range(w)] for y in range(h)]
    # Neutral panels may touch in an L shape. Connected-component bounding boxes
    # then include the patterned gap. Maximal ALL-neutral rectangles cannot.
    for _ in range(8):
        heights=[0]*w;best=None;best_area=0
        for y in range(h):
            heights=[heights[x]+1 if mask[y][x] else 0 for x in range(w)];stack=[]
            for x in range(w+1):
                current=heights[x] if x<w else 0;left=x
                while stack and stack[-1][1]>current:
                    start,tall=stack.pop();area=(x-start)*tall
                    if area>best_area:best_area=area;best=(start,y-tall+1,x,y+1)
                    left=start
                if current and (not stack or stack[-1][1]<current):stack.append((left,current))
        if best is None or best_area<w*h*.035:break
        left,top,right,bottom=best
        for y in range(top,bottom):
            for x in range(left,right):mask[y][x]=False
        if right-left<15 or bottom-top<8:continue
        pad=min(12,(right-left)*width/w*.035,(bottom-top)*height/h*.08)
        result.append(dict(x=left*width/w+pad,y=top*height/h+pad,w=(right-left)*width/w-pad*2,h=(bottom-top)*height/h-pad*2))
    return result

def busy_text_background(image,item,width,height):
    if item.get('size',24)>20 or item.get('w',0)<30 or item.get('h',0)<10:return False
    bounds=(max(0,round(item['x']*image.width/width)),max(0,round(item['y']*image.height/height)),min(image.width,round((item['x']+item['w'])*image.width/width)),min(image.height,round((item['y']+item['h'])*image.height/height)))
    if bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:return False
    sample=image.crop(bounds).resize((24,12),Image.Resampling.NEAREST).convert('RGB');pixels=sample.load();edges=0;values=[];channels=[[],[],[]]
    for y in range(12):
        for x in range(24):
            p=pixels[x,y];values.append(sum(a*b for a,b in zip(p,(.2126,.7152,.0722)))/255)
            for channel in range(3):channels[channel].append(p[channel]/255)
            if x and max(abs(a-b) for a,b in zip(p,pixels[x-1,y]))>45:edges+=1
    values.sort()
    for channel in channels:channel.sort()
    # Saturated orange/red/cyan artwork can have similar luminance despite
    # strong visible color boundaries. Median contrast alone misses it.
    color_spread=max(channel[len(channel)*9//10]-channel[len(channel)//10] for channel in channels)
    return edges/(23*12)>.08 and (values[len(values)*9//10]-values[len(values)//10]>.20 or color_spread>.20)
