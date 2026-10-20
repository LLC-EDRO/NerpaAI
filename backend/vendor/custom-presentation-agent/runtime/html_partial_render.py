"""Re-render repaired HTML pages, retaining exact accepted unchanged pages."""
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from lxml import html,etree
import pymupdf


def render_changed_pages(scenes,template,folder,output,images,deadline,baseline,changed):
    from runtime.html_deck import browser_render
    previous=baseline.get('slides',[])
    numbers=sorted({n for n in changed if type(n) is int and 1<=n<=len(scenes)})
    if len(previous)!=len(scenes) or not numbers:raise ValueError('html_partial_identity')
    selected=set(numbers)
    for i in range(len(scenes)):
        if i+1 not in selected:scenes[i]=deepcopy(previous[i]['native']['html'])
    accepted=html.document_fromstring((folder/'html-proof.html').read_text())
    sections=accepted.xpath('//body/section[@data-slide]')
    if len(sections)!=len(scenes):raise ValueError('html_partial_pages')
    with tempfile.TemporaryDirectory(prefix='html-changed-',dir=output.parent) as temporary:
        work=Path(temporary)
        changed_scenes=[scenes[n-1] for n in numbers]
        warnings=browser_render(changed_scenes,template,folder,work,images,deadline)
        current=html.document_fromstring((work/'presentation.html').read_text())
        replacements=current.xpath('//body/section[@data-slide]')
        if len(replacements)!=len(numbers):raise ValueError('html_partial_pages')
        for local,number in enumerate(numbers):
            index=number-1;replacement=replacements[local];replacement.set('data-slide',str(index))
            sections[index].getparent().replace(sections[index],replacement)
            shutil.copyfile(work/f'slide-{local}.png',output/f'slide-{index}.png')
            art=work/f'authored-background-{local}.png'
            if art.is_file():
                shutil.copyfile(art,output/f'authored-background-{index}.png');scenes[index]['authoredBackground']=f'authored-background-{index}.png'
        for index in range(len(scenes)):
            if index+1 in selected:continue
            shutil.copyfile(folder/f'html-proof-slide-{index}.png',output/f'slide-{index}.png')
            art=folder/f'html-proof-background-{index}.png'
            if art.is_file():shutil.copyfile(art,output/f'authored-background-{index}.png')
        (output/'presentation.html').write_text('<!doctype html>\n'+etree.tostring(accepted,encoding='unicode',method='html'))
        with pymupdf.open(folder/'html-proof.pdf') as original,pymupdf.open(work/'html-preview.pdf') as repaired,pymupdf.open() as merged:
            if len(original)!=len(scenes) or len(repaired)!=len(numbers):raise ValueError('html_partial_pages')
            for index in range(len(scenes)):
                local=numbers.index(index+1) if index+1 in selected else index
                merged.insert_pdf(repaired if index+1 in selected else original,from_page=local,to_page=local)
            merged.save(output/'html-preview.pdf',garbage=4,deflate=True)
    warnings=[w for w in baseline.get('warnings',[]) if w.get('slide') not in selected]+warnings
    return scenes,warnings
