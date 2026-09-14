"""PDF 추출 프로세스 — PyMuPDF를 io 워커의 여러 스레드에서 함께 호출하지 않는다."""
import sys

import pymupdf


def extract(data: bytes) -> str:
    pages = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if len(doc) > 100:
            raise ValueError("공고 PDF가 100쪽을 초과합니다")
        for page in doc:
            text = page.get_text(sort=True).strip()
            ocr = len(text) < 30
            if ocr:
                tp = page.get_textpage_ocr(language="kor+eng", dpi=300, full=True)
                text = page.get_text(textpage=tp, sort=True).strip()
            if text:
                pages.append(f"[PDF {page.number + 1}쪽{' · OCR 오인식 가능' if ocr else ''}]\n{text}")
    if not pages:
        raise ValueError("공고 PDF의 본문을 인식하지 못했습니다")
    return "\n\n".join(pages)


if __name__ == "__main__":
    print(extract(sys.stdin.buffer.read()))
