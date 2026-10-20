"""One bounded invocation, JSON stdin/stdout. No provider calls or inherited app config."""
import json
import sys
import subprocess
from pathlib import Path
from runtime.render import render
from runtime.fonts import effective_source,requested_font_names,font_environment_fingerprint
from runtime.layout_metadata import layout_metadata

def main():
    request = json.load(sys.stdin)
    folder = Path(request['folder']).resolve()
    source = folder/'source.pptx'
    action = request['action']
    if action == 'assemble':
        from runtime.assemble import assemble
        output = Path(request['output']).resolve()
        output.mkdir(parents=True, exist_ok=True)
        return assemble(source, folder, request['layoutIds'], output/'presentation.pptx')
    if action == 'html_template':
        from runtime.html_deck import prepare_template
        return prepare_template(folder, request['soffice'],request.get('reuseArtwork',False),request.get('profilesOnly',False),request.get('selectedLayoutIds',[]))
    if action == 'html_export':
        from runtime.html_deck import export_deck
        return export_deck(folder, request)
    if action == 'pdf_preview':
        from runtime.pdf_preview import pdf_preview
        return pdf_preview(folder,request)
    if action == 'html_editor_background':
        from runtime.html_editor_background import html_editor_background
        return html_editor_background(folder,request)
    if action == 'font_cache':
        from runtime.font_cache import build_font_cache
        return build_font_cache(Path(request['output']),request['fontDirectories'])
    if action == 'font_requirements':
        return dict(families=requested_font_names(source))
    if action == 'font_environment':
        return dict(fingerprint=font_environment_fingerprint(requested_font_names(source)))
    if action == 'layout_metadata':
        return layout_metadata(folder,include_budgets=True)
    if action == 'analyze':
        # Release every parser allocation before LibreOffice starts. Python's
        # allocator can retain hundreds of MB even after model objects die.
        worker = subprocess.run([sys.executable, '-m', 'runtime.analysis_worker', str(source), str(folder)],
                                capture_output=True, text=True, timeout=180, check=False)
        if worker.returncode:
            raise ValueError('pptx_resource_limit' if worker.returncode == -9 else 'pptx_analysis_failed')
        result=json.loads(worker.stdout)
        if result.get('error'):return result
        value=json.loads((folder/'analysis.json').read_text())
        count = render(effective_source(source,folder,value), folder/'previews', request['soffice'])
        if count != len(value['layouts']): raise ValueError('pptx_preview_count_mismatch')
        return value
    raise ValueError('pptx_unknown_operation')

if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as error:
        # Sanitized diagnostics only, not XML, user text, paths, or environment.
        reason = str(error) if isinstance(error, ValueError) and str(error).startswith('pptx_') else type(error).__name__
        print(json.dumps(dict(error=reason)))
        sys.exit(1)
