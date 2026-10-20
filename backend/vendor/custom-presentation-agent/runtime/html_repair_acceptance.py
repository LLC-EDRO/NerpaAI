"""Keep the better measured slide when an optional model repair regresses it."""
from copy import deepcopy
from pathlib import Path
import shutil
import pymupdf
from lxml import html,etree

WEIGHTS={'html_text_overflow':5,'html_text_too_small':5,'html_native_bounds':8,'html_low_contrast':5,'html_busy_background':5,
         'html_source_icon_overlap':5,'html_author_recovered':10,'html_text_overlap':6,'html_source_art_overlap':2,
         'html_source_container_empty':5,'html_source_container_drift':5,'html_source_padding':5,
         'html_source_image_overlap':8,'html_source_row_empty':5,'html_source_structure_removed':40,'html_source_visual_abandoned':30,'html_source_figure_too_small':8}

def repair_score(warnings,number):
    findings={(w.get('reason'),w.get('key','')) for w in warnings if w.get('slide')==number}
    return sum(WEIGHTS.get(reason,0) for reason,key in findings)

def accept_repair(scenes,warnings,baseline,changed,folder,output):
    previous=baseline.get('slides',[]);old_warnings=baseline.get('warnings',[])
    if len(previous)!=len(scenes):raise ValueError('html_repair_baseline_identity')
    reverted=[n for n in changed if 1<=n<=len(scenes) and repair_score(warnings,n)>repair_score(old_warnings,n)]
    if not reverted:return scenes,warnings,[]
    # Each HTML shadow tree is self-contained. Restore its matching PDF page,
    # preview, artwork and measured scene together, with no extra browser pass.
    current=html.document_fromstring((output/'presentation.html').read_text())
    original=html.document_fromstring((folder/'html-proof.html').read_text())
    a=current.xpath('//body/section[@data-slide]');b=original.xpath('//body/section[@data-slide]')
    if len(a)!=len(scenes) or len(b)!=len(scenes):raise ValueError('html_repair_page_identity')
    for number in reverted:
        index=number-1;scene=previous[index].get('native',{}).get('html')
        if not isinstance(scene,dict) or scene.get('index')!=index:raise ValueError('html_repair_scene_identity')
        scenes[index]=deepcopy(scene);scenes[index]['repairRejected']=True
        a[index].getparent().replace(a[index],deepcopy(b[index]))
        shutil.copyfile(folder/f'html-proof-slide-{index}.png',output/f'slide-{index}.png')
        if scenes[index].get('authoredBackground'):
            shutil.copyfile(folder/f'html-proof-background-{index}.png',output/f'authored-background-{index}.png')
    (output/'presentation.html').write_text('<!doctype html>\n'+etree.tostring(current,encoding='unicode',method='html'))
    with pymupdf.open(output/'html-preview.pdf') as candidate,pymupdf.open(folder/'html-proof.pdf') as original_pdf,pymupdf.open() as merged:
        if len(candidate)!=len(scenes) or len(original_pdf)!=len(scenes):raise ValueError('html_repair_pdf_identity')
        for index in range(len(scenes)):merged.insert_pdf(original_pdf if index+1 in reverted else candidate,from_page=index,to_page=index)
        target=output/'html-accepted.pdf';merged.save(target,garbage=4,deflate=True);target.replace(output/'html-preview.pdf')
    warnings=[w for w in warnings if w.get('slide') not in reverted]+[w for w in old_warnings if w.get('slide') in reverted]
    warnings += [dict(slide=n,reason='html_visual_repair_reverted',message='Предложенная правка ухудшала измеренную вёрстку; сохранён предыдущий вариант этого слайда.') for n in reverted]
    return scenes,warnings,reverted
