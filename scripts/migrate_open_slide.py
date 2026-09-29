"""Copy approved native portfolio PPTX elements into editable Open Slide JSX.

This is a one-time, non-overwriting migration, not a general PowerPoint importer.
The reviewed source uses text boxes, solid rectangles and straight connectors.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data/application-pack-20260929"
OUTPUT = ROOT / "data/application-slide-studio"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
FONT = "Noto Sans CJK KR"


def number(value, divisor=6350):
    """EMU -> 2x source points (the 1920x1080 Open Slide canvas)."""
    return round(float(value) / divisor, 6)


def js(value):
    return json.dumps(value, ensure_ascii=False)


def required(node, query):
    found = node.find(query, NS)
    if found is None:
        raise ValueError(f"Unsupported PPTX: missing {query}")
    return found


def color(node):
    value = required(node, "a:solidFill/a:srgbClr").get("val")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value or ""):
        raise ValueError("Unsupported color")
    return "#" + value


def relationships(archive, part):
    relative = str(PurePosixPath(part).parent / "_rels" / (PurePosixPath(part).name + ".rels"))
    if relative not in archive.namelist():
        return {}
    return {r.get("Id"): r.attrib for r in ET.fromstring(archive.read(relative))}


def read_deck(path):
    pages = []
    with ZipFile(path) as archive:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        size = required(presentation, "p:sldSz")
        if (number(size.get("cx")), number(size.get("cy"))) != (1920, 1080):
            raise ValueError("Only the approved 960x540-point portfolios can be migrated")
        rels = relationships(archive, "ppt/presentation.xml")
        for slide_id in required(presentation, "p:sldIdLst"):
            relationship = rels[slide_id.get("{" + NS["r"] + "}id")]
            part = posixpath.normpath("ppt/" + relationship["Target"])
            slide = ET.fromstring(archive.read(part))
            page = {"background": color(required(slide, "p:cSld/p:bg/p:bgPr")), "shapes": []}
            slide_rels = relationships(archive, part)
            for element in required(slide, "p:cSld/p:spTree"):
                kind = element.tag.rsplit("}", 1)[-1]
                if kind in ("nvGrpSpPr", "grpSpPr"):
                    continue
                if kind not in ("sp", "cxnSp"):
                    raise ValueError(f"Unsupported shape: {kind}")
                props = required(element, "p:spPr")
                transform = required(props, "a:xfrm")
                if transform.get("rot", "0") != "0":
                    raise ValueError("Unsupported rotation")
                offset, extent = required(transform, "a:off"), required(transform, "a:ext")
                shape = {"x": number(offset.get("x")), "y": number(offset.get("y")),
                         "width": number(extent.get("cx")), "height": number(extent.get("cy"))}
                info = required(element, "p:nvCxnSpPr/p:cNvPr" if kind == "cxnSp" else "p:nvSpPr/p:cNvPr")
                shape["id"] = info.get("id")
                if kind == "cxnSp":
                    line = required(props, "a:ln")
                    shape.update(type="line", color=color(line), stroke=number(line.get("w")),
                                 flipH=transform.get("flipH") == "1", flipV=transform.get("flipV") == "1")
                    for end in ("headEnd", "tailEnd"):
                        arrow = line.find("a:" + end, NS)
                        value = arrow.get("type", "none") if arrow is not None else "none"
                        if value not in ("none", "triangle"):
                            raise ValueError("Unsupported arrow")
                        shape[end] = value
                elif required(element, "p:nvSpPr/p:cNvSpPr").get("txBox") == "1":
                    body = required(element, "p:txBody")
                    body_props = required(body, "a:bodyPr")
                    if any(body_props.get(k, "0") != "0" for k in ("lIns", "rIns", "tIns", "bIns")):
                        raise ValueError("Unsupported text margins")
                    shape.update(type="text", paragraphs=[])
                    for paragraph in body.findall("a:p", NS):
                        pprops = required(paragraph, "a:pPr")
                        spacing = required(pprops, "a:lnSpc/a:spcPct")
                        para = {"align": {"l": "left", "ctr": "center", "r": "right"}[pprops.get("algn", "l")],
                                "spacing": number(spacing.get("val"), 100000), "runs": []}
                        for run in paragraph.findall("a:r", NS):
                            rprops = required(run, "a:rPr")
                            font = required(rprops, "a:latin").get("typeface")
                            if font != FONT:
                                raise ValueError(f"Unexpected font: {font}")
                            para["runs"].append({"text": required(run, "a:t").text or "",
                                                 "size": number(rprops.get("sz"), 50),
                                                 "bold": rprops.get("b", "0") == "1", "color": color(rprops)})
                        if not para["runs"] or paragraph.find("a:br", NS) is not None:
                            raise ValueError("Unsupported paragraph structure")
                        shape["paragraphs"].append(para)
                    hyperlink = info.find("a:hlinkClick", NS)
                    if hyperlink is not None:
                        shape["link"] = slide_rels[hyperlink.get("{" + NS["r"] + "}id")]["Target"]
                else:
                    geometry = required(props, "a:prstGeom")
                    if geometry.get("prst") not in ("rect", "roundRect"):
                        raise ValueError("Unsupported geometry")
                    shape.update(type="rect", color=color(props), radius=0)
                    if geometry.get("prst") == "roundRect":
                        adjustment = required(geometry, "a:avLst/a:gd").get("fmla")
                        if not re.fullmatch(r"val \d+", adjustment or ""):
                            raise ValueError("Unsupported rounded rectangle adjustment")
                        shape["radius"] = round(min(shape["width"], shape["height"]) * int(adjustment.split()[1]) / 100000, 6)
                page["shapes"].append(shape)
            pages.append(page)
    if not pages:
        raise ValueError("Empty portfolio")
    return pages


def render_shape(shape, prefix):
    style = {"position": "absolute", "left": shape["x"], "top": shape["y"],
             "width": shape["width"], "height": shape["height"], "boxSizing": "border-box"}
    element_id = prefix + "-shape-" + shape["id"]
    if shape["type"] == "rect":
        style.update(backgroundColor=shape["color"], borderRadius=shape["radius"])
        return f'    <div data-source-shape={{{js(element_id)}}} style={{{js(style)}}} />'
    if shape["type"] == "line":
        width, height = shape["width"], shape["height"]
        # Export captures the SVG viewport; include the stroke and arrowheads inside it.
        padding = round(shape["stroke"] * 3, 6)
        style.update(left=round(shape["x"] - padding, 6), top=round(shape["y"] - padding, 6),
                     width=round(width + padding * 2, 6), height=round(height + padding * 2, 6))
        x1, x2 = (width, 0) if shape["flipH"] else (0, width)
        y1, y2 = (height, 0) if shape["flipV"] else (0, height)
        x1, y1, x2, y2 = (round(value + padding, 6) for value in (x1, y1, x2, y2))
        markers = []
        attributes = []
        for end, attribute in (("headEnd", "markerStart"), ("tailEnd", "markerEnd")):
            if shape[end] == "triangle":
                marker_id = element_id + "-" + end
                markers.append(f'<marker id={{{js(marker_id)}}} markerWidth="3" markerHeight="3" refX="3" refY="1.5" orient="auto-start-reverse" markerUnits="strokeWidth"><path d="M 0 0 L 3 1.5 L 0 3 Z" fill={{{js(shape["color"])}}} /></marker>')
                attributes.append(f'{attribute}={{{js("url(#" + marker_id + ")")}}}')
        return (f'    <svg data-source-shape={{{js(element_id)}}} style={{{js(style)}}} aria-hidden="true">\n'
                f'      <defs>{"".join(markers)}</defs>\n'
                f'      <line x1={{{x1}}} y1={{{y1}}} x2={{{x2}}} y2={{{y2}}} stroke={{{js(shape["color"])}}} strokeWidth={{{shape["stroke"]}}} {" ".join(attributes)} />\n'
                '    </svg>')
    style.update(fontFamily=FONT, whiteSpace="pre-wrap", overflowWrap="normal", wordBreak="normal",
                 textDecoration="none", padding=0, margin=0)
    tag = "a" if "link" in shape else "div"
    link = f' href={{{js(shape["link"])}}}' if tag == "a" else ""
    lines = [f'    <{tag} data-source-shape={{{js(element_id)}}}{link} style={{{js(style)}}}>']
    for para in shape["paragraphs"]:
        size = max(run["size"] for run in para["runs"])
        pstyle = {"margin": 0, "padding": 0, "fontSize": size, "lineHeight": para["spacing"],
                  "textAlign": para["align"], "minHeight": size * para["spacing"]}
        if len(para["runs"]) == 1:
            run = para["runs"][0]
            pstyle.update(fontSize=run["size"], fontWeight=700 if run["bold"] else 400, color=run["color"])
            lines.append(f'      <div style={{{js(pstyle)}}}>{{{js(run["text"])}}}</div>')
            continue
        lines.append(f'      <div style={{{js(pstyle)}}}>')
        for run in para["runs"]:
            rstyle = {"fontSize": run["size"], "fontWeight": 700 if run["bold"] else 400, "color": run["color"]}
            lines.append(f'        <span style={{{js(rstyle)}}}>{{{js(run["text"])}}}</span>')
        lines.append('      </div>')
    lines.append(f'    </{tag}>')
    return "\n".join(lines)


def render_source(pages, entry, slide_id, generated_at):
    parts = ["import type { Page, SlideMeta } from '@open-slide/core';",
             "import '../../assets/fonts.css';", ""]
    for index, page in enumerate(pages, 1):
        style = {"position": "relative", "width": "100%", "height": "100%", "backgroundColor": page["background"], "fontFamily": FONT}
        parts.extend([f"const Page{index}: Page = () => (", f'  <div style={{{js(style)}}}>'])
        parts.extend(render_shape(shape, f"{slide_id}-page-{index}") for shape in page["shapes"])
        parts.extend(["  </div>", ");", ""])
    title = "기본 포트폴리오" if entry["id"] == "base" else entry["company"] + " 포트폴리오"
    parts.extend(["export const meta: SlideMeta = {", f'  title: {js(title)},',
                  f"  createdAt: {js(generated_at)},", "};",
                  "export const notes: (string | undefined)[] = [",
                  "  " + js("\n".join(entry.get("source_urls", []))) + ",",
                  *["  undefined," for _ in pages[1:]], "];",
                  "export default [" + ", ".join(f"Page{i}" for i in range(1, len(pages) + 1)) + "] satisfies Page[];", ""])
    return "\n".join(parts)


def migrate(pack=PACK, output_root=OUTPUT, ids=None):
    pack, output_root = Path(pack).resolve(), Path(output_root).resolve()
    entries = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    if ids is not None:
        unknown = set(ids) - {entry["id"] for entry in entries}
        if unknown:
            raise ValueError(f"Unknown package ids: {sorted(unknown)}")
        entries = [entry for entry in entries if entry["id"] in ids]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    plans, manifest, slide_ids = [], [], set()
    if (output_root / "manifest.json").exists():
        raise FileExistsError("Output manifest already exists; use a fresh output root to preserve edits")
    for entry in entries:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", entry["id"]):
            raise ValueError("Invalid package id")
        slide_id = "portfolio-" + entry["id"].lower().replace("_", "-")
        if slide_id in slide_ids:
            raise ValueError("Duplicate slide id")
        slide_ids.add(slide_id)
        destination = output_root / "slides" / slide_id / "index.tsx"
        if destination.exists():
            raise FileExistsError(f"Will not overwrite editable source: {destination}")
        sources = [file for file in entry["files"] if file["path"].endswith("_포트폴리오.pptx")]
        if len(sources) != 1:
            raise ValueError(f"Expected one portfolio for {entry['id']}")
        source = (pack / sources[0]["path"]).resolve()
        if not source.is_relative_to(pack):
            raise ValueError("Source outside application pack")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != sources[0]["sha256"]:
            raise ValueError(f"Approved PPTX hash mismatch: {source}")
        pages = read_deck(source)
        plans.append((destination, render_source(pages, entry, slide_id, generated_at)))
        manifest.append({"id": entry["id"], "ids": entry["ids"], "company": entry["company"],
                         "title": "기본 포트폴리오" if entry["id"] == "base" else entry["company"] + " 포트폴리오", "source_urls": entry["source_urls"],
                         "slideId": slide_id, "pages": len(pages), "sourcePptx": str(source),
                         "sha256": digest, "generatedAt": generated_at})
    for destination, source in plans:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(source)
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "manifest.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    parser.add_argument("--ids", help="Comma-separated canonical package ids; default: all")
    args = parser.parse_args()
    result = migrate(output_root=args.output_root, ids=args.ids.split(",") if args.ids else None)
    print(json.dumps({"decks": len(result), "pages": sum(item["pages"] for item in result), "output": str(args.output_root)}, ensure_ascii=False))
