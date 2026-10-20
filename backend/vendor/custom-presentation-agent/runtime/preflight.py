"""One readiness rule for upload, cached layout discovery and checkout.

Probe overflow is advisory: it depends on the replacement text and paragraph
styles actually used. Only unsupported source structure/fonts block discovery.
Every generated payload must still pass the physical fit and occlusion checks.
Never shrink source typography, change geometry or suppress security checks.
"""
from runtime.text_frames import TemplateTextFrame

OVERFLOW_WARNING = 'В исходном текстовом поле недостаточно места при его размере шрифта. Для автоматического заполнения используется другой макет этого PPTX.'
UNVERIFIABLE_WARNING = 'Не удалось проверить исходное оформление текстового поля. Макет сохранён для просмотра.'
FORMATTING_WARNING = 'В текстовом поле есть неподдерживаемые параметры оформления. Макет сохранён для просмотра.'

def layout_frame_issues(layout, frames, fitter):
    issues = []
    for slot in layout['slots']:
        key = slot['key']
        if key not in frames:
            raise ValueError('pptx_frame_metadata_missing')
        frame = TemplateTextFrame.model_validate(frames[key])
        if not frame.paragraphs:
            issues.append(dict(sourceSlideId=layout['id'], key=key, paragraph=0,
                               reason='unverifiable', details=['source_text_frame_missing']))
        for index, report in enumerate(fitter.probe(frame, 'I')):
            if report.status != 'fits':
                issues.append(dict(sourceSlideId=layout['id'], key=key, paragraph=index,
                                   reason=report.status, details=report.reason_codes))
    return issues

def layout_readiness(layout, frames, fitter):
    issues = layout_frame_issues(layout, frames, fitter)
    warnings = [w for w in layout.get('warnings', []) if w not in (OVERFLOW_WARNING, UNVERIFIABLE_WARNING)]
    old_issues = layout.get('preflightIssues', [])
    recovered_geometry = bool(old_issues) and all(
        issue.get('details') == ['nonrectangular_text_frame_unsupported'] for issue in old_issues
    ) and not any(issue['reason'] != 'overflow' for issue in issues)
    if recovered_geometry:
        warnings = [w for w in warnings if w != FORMATTING_WARNING]
    # Recover old cached uploads only when our former probe was the sole gate.
    # Unknown explicit disables, SmartArt and parser failures remain disabled.
    source_usable = layout.get('structurallyUsable', bool(layout.get('usable')) or (
        bool(layout.get('preflightIssues')) and not warnings))
    if recovered_geometry and not warnings:
        source_usable = True
    blocking = [issue for issue in issues if issue['reason'] != 'overflow']
    if blocking:
        warnings.append(UNVERIFIABLE_WARNING)
    return dict(usable=bool(source_usable) and bool(layout['slots']) and not blocking,
                structurallyUsable=bool(source_usable), warnings=list(dict.fromkeys(warnings)),
                preflightIssues=blocking, contentFitIssues=[issue for issue in issues if issue['reason'] == 'overflow'])
