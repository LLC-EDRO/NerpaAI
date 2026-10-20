"""Shared display precision and truthful scales for HTML and editable charts.
Raw observations and embedded workbooks are never rounded or rescaled.
"""
import math


def number_label(value):
    value=float(value)
    magnitude=abs(value)
    if 0<magnitude<1e-6:return format(value,'.2g').replace('.',',')
    suffix=''
    for threshold,label in ((1e12,' трлн'),(1e9,' млрд'),(1e6,' млн'),(1e4,' тыс.')):
        if magnitude>=threshold:
            value/=1000 if threshold==1e4 else threshold
            suffix=label
            break
    if not value:return '0'
    digits=max(0,min(6,2-math.floor(math.log10(abs(value))))) if abs(value)<1 else 2
    return ('%.*f'%(digits,value)).rstrip('0').rstrip('.').replace('.',',')+suffix if digits else ('%.0f'%value)+suffix


def value_domain(data):
    values=[float(v) for series in data['series'] for v in series['values']]
    low,high=min(values),max(values)
    # Bars encode magnitude by length and always include zero. A time series
    # encodes position: use a labelled local scale to reveal the actual change.
    if data['type'] not in ('line','xy'):
        low=min(0,low);high=max(0,high)
        return low,high if high>low else low+1
    span=high-low
    if not span:span=max(abs(high)*.1,1)
    pad=span*.12
    low-=pad;high+=pad
    raw=(high-low)/4;power=10**math.floor(math.log10(raw))
    step=next(m for m in (1,2,2.5,5,10) if m*power>=raw)*power
    return math.floor(low/step)*step,math.ceil(high/step)*step
