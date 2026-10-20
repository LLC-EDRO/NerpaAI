"""Rasterize one public gallery page. No editing or presentation generation."""
from pathlib import Path
import pymupdf


def pdf_preview(folder,request):
    output=Path(request['output']);output.mkdir(parents=True,exist_ok=True)
    with pymupdf.open(Path(folder)/'previews/presentation.pdf') as source:
        page=request['page']
        if type(page) is not int or not 0<=page<len(source):raise ValueError('pptx_preview_page_invalid')
        source[page].get_pixmap(matrix=pymupdf.Matrix(1280/source[page].rect.width,1280/source[page].rect.width),alpha=False).save(output/'slide-0.png')
    return dict(page=page)
