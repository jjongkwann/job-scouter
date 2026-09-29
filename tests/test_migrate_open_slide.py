import hashlib
import importlib.util
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migrate_open_slide", ROOT / "scripts/migrate_open_slide.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


@pytest.fixture
def native_pack(tmp_path):
    """Use a tiny native OOXML fixture with styles, blank lines, links and a flipped connector."""
    pack = tmp_path / "pack"
    pack.mkdir()
    source = pack / "원본_포트폴리오.pptx"
    a, p, r = (migration.NS[k] for k in ("a", "p", "r"))
    run = '<a:r><a:rPr sz="1500" b="1"><a:solidFill><a:srgbClr val="123456"/></a:solidFill><a:latin typeface="Noto Sans CJK KR"/></a:rPr><a:t>{}</a:t></a:r>'
    paragraph = '<a:p><a:pPr algn="r"><a:lnSpc><a:spcPct val="135000"/></a:lnSpc></a:pPr>{}</a:p>'
    body = ''.join(paragraph.format(run.format(text)) for text in ['검증된 &lt;사실&gt;', '', '둘째 줄'])
    xfrm = '<a:xfrm><a:off x="127000" y="254000"/><a:ext cx="1270000" cy="508000"/></a:xfrm>'
    slide = f'''<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{r}"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></p:bgPr></p:bg><p:spTree>
    <p:sp><p:nvSpPr><p:cNvPr id="2"><a:hlinkClick r:id="link"/></p:cNvPr><p:cNvSpPr txBox="1"/></p:nvSpPr><p:spPr>{xfrm}</p:spPr><p:txBody><a:bodyPr lIns="0" rIns="0" tIns="0" bIns="0"/>{body}</p:txBody></p:sp>
    <p:sp><p:nvSpPr><p:cNvPr id="3"/><p:cNvSpPr/></p:nvSpPr><p:spPr>{xfrm}<a:prstGeom prst="roundRect"><a:avLst><a:gd fmla="val 6000"/></a:avLst></a:prstGeom><a:solidFill><a:srgbClr val="EAF3EE"/></a:solidFill></p:spPr></p:sp>
    <p:cxnSp><p:nvCxnSpPr><p:cNvPr id="4"/></p:nvCxnSpPr><p:spPr><a:xfrm flipV="1"><a:off x="127000" y="254000"/><a:ext cx="1270000" cy="508000"/></a:xfrm><a:ln w="16510"><a:solidFill><a:srgbClr val="28624B"/></a:solidFill><a:tailEnd type="triangle"/></a:ln></p:spPr></p:cxnSp>
    </p:spTree></p:cSld></p:sld>'''
    with ZipFile(source, 'w') as archive:
        archive.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId r:id="slide"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>')
        archive.writestr('ppt/_rels/presentation.xml.rels', '<Relationships><Relationship Id="slide" Target="slides/slide1.xml"/></Relationships>')
        archive.writestr('ppt/slides/slide1.xml', slide)
        archive.writestr('ppt/slides/_rels/slide1.xml.rels', '<Relationships><Relationship Id="link" Target="https://example.com/source"/></Relationships>')
    entry = {'id': 'remember_123', 'ids': ['remember_123', '456'], 'company': '테스트 회사',
             'source_urls': ['https://example.com/jd'], 'files': [{'path': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}
    (pack / 'manifest.json').write_text(json.dumps([entry], ensure_ascii=False))
    return pack, source, entry


def test_preserves_native_text_style_geometry_links_and_arrow(native_pack, tmp_path):
    pack, source, entry = native_pack
    pages = migration.read_deck(source)
    text, rectangle, line = pages[0]['shapes']
    assert (text['x'], text['y'], text['width'], text['height']) == (20, 40, 200, 80)
    assert [p['runs'][0]['text'] for p in text['paragraphs']] == ['검증된 <사실>', '', '둘째 줄']
    assert text['paragraphs'][0] == {'align': 'right', 'spacing': 1.35, 'runs': [{'text': '검증된 <사실>', 'size': 30, 'bold': True, 'color': '#123456'}]}
    assert text['link'] == 'https://example.com/source'
    assert rectangle['radius'] == 4.8 and line['flipV'] and line['stroke'] == 2.6
    out = tmp_path / 'studio'
    manifest = migration.migrate(pack, out)
    jsx = (out / 'slides/portfolio-remember-123/index.tsx').read_text()
    assert 'const Page1: Page' in jsx and 'export default [Page1] satisfies Page[]' in jsx
    assert '<line x1={7.8} y1={87.8} x2={207.8} y2={7.8}' in jsx
    svg_style = json.loads(re.search(r'<svg[^\n]+style=\{(\{[^\n]+\})\}', jsx).group(1))
    assert svg_style['left'] + 7.8 == pytest.approx(text['x'])
    assert svg_style['top'] + 87.8 == pytest.approx(text['y'] + text['height'])
    assert svg_style['width'] == 215.6 and svg_style['height'] == 95.6
    assert 'overflow' not in svg_style
    horizontal = migration.render_shape({**line, 'height': 0}, 'horizontal')
    assert '"height": 15.6' in horizontal and 'y1={7.8}' in horizontal and 'y2={7.8}' in horizontal
    assert 'markerEnd=' in jsx and 'M 0 0 L 3 1.5 L 0 3 Z' in jsx
    assert '<img' not in jsx and '.map(' not in jsx
    assert '{""}</div>' in jsx and '../../assets/fonts.css' in jsx
    assert '<span' not in jsx
    paragraph = next(line for line in jsx.splitlines() if '{"검증된 <사실>"}' in line)
    assert '"fontSize": 30.0' in paragraph and '"fontWeight": 700' in paragraph and '"color": "#123456"' in paragraph
    assert manifest[0]['ids'] == entry['ids'] and manifest[0]['pages'] == 1
    assert manifest[0]['sha256'] == entry['files'][0]['sha256']
    assert json.loads((out / 'manifest.json').read_text()) == manifest


def test_existing_sources_and_hash_changes_fail_without_overwriting(native_pack, tmp_path):
    pack, source, _ = native_pack
    out = tmp_path / 'studio'
    target = out / 'slides/portfolio-remember-123/index.tsx'
    target.parent.mkdir(parents=True)
    target.write_text('user edited')
    with pytest.raises(FileExistsError):
        migration.migrate(pack, out)
    assert target.read_text() == 'user edited' and not (out / 'manifest.json').exists()
    source.write_bytes(source.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        migration.migrate(pack, tmp_path / 'new')


def test_unknown_ids_fail_before_writes(native_pack, tmp_path):
    pack, _, _ = native_pack
    out = tmp_path / 'unknown'
    with pytest.raises(ValueError, match='Unknown package'):
        migration.migrate(pack, out, ['missing'])
    assert not out.exists()


def test_actual_base_and_job_text_is_copied_verbatim(tmp_path):
    if not (migration.PACK / 'manifest.json').exists():
        pytest.skip('Reviewed local artifact pack is not part of the repository')
    manifest = migration.migrate(output_root=tmp_path / 'studio', ids=['base', '385747'])
    assert [(entry['id'], entry['pages']) for entry in manifest] == [('base', 8), ('385747', 7)]
    for entry in manifest:
        jsx = (tmp_path / 'studio/slides' / entry['slideId'] / 'index.tsx').read_text()
        emitted = [json.loads(value) for value in re.findall(r'<(?:div|span) style=\{[^\n]+\}>\{("(?:\\.|[^"\\])*")\}</(?:div|span)>', jsx)]
        original = []
        with ZipFile(entry['sourcePptx']) as archive:
            for index in range(1, entry['pages'] + 1):
                slide = ET.fromstring(archive.read(f'ppt/slides/slide{index}.xml'))
                original.extend(node.text or '' for node in slide.findall('.//a:r/a:t', migration.NS))
        assert emitted == original
