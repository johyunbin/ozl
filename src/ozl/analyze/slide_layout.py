#!/usr/bin/env python3
"""슬라이드 한 장의 레이아웃 판정 — 문자 인식으로 글 영역을 지운 뒤 남는 잉크를 '그림'으로 본다 (Phase 2A).

style_measure.image_boxes() 는 꽉 찬 사각 사진만 잡아 흰 배경 위의 로고·오려낸 인물·문서 캡처·도표를 놓쳤다(독립 검증: text_only 16장 중 14장이 실제로는 그림 있음).
여기서는 ① 흰색이 아닌 픽셀 ② 에서 제목·본문 글줄 상자를 지우고 ③ 8px 블록으로 뭉쳐 연결 성분을 구한 뒤 ④ 넓이가 충분한 성분을 그림으로 본다.
반환 layout: text_only · image_left · image_right · image_full · image_pair · image_stack(그림 위/아래 + 글) · media(흰 배경이 아닌 전체 화면)
"""
from __future__ import annotations

import cv2
import numpy as np

BLOCK = 8
MIN_AREA = 0.012   # 그림 성분 최소 넓이(프레임 대비)
BODY_H = (26, 52)  # 본문 크기 글줄의 문자 인식 상자 높이(px · 1152×680 기준)


def graphics(a: np.ndarray, text_boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """a: HxWx3 uint8/int. text_boxes: (x, y, w, h) 글줄 상자(제목 포함). 반환: 그림 성분 (x0, y0, x1, y1)."""
    a = a.astype(np.int16)
    h, w, _ = a.shape
    mx, mn = a.max(axis=2), a.min(axis=2)
    ink = (a.mean(axis=2) < 240) | ((mx - mn) > 25)
    for x, y, bw, bh in text_boxes:
        ink[max(0, y - 4) : y + bh + 4, max(0, x - 6) : x + bw + 6] = False
    # 1~2px 가는 선 제거: 파워포인트 선택 상자의 점선·필기 선·인식 못 한 가는 글자가 성분을 하나로 이어 붙이는 것을 막는다
    ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    hb, wb = h // BLOCK, w // BLOCK
    dens = ink[: hb * BLOCK, : wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK).mean(axis=(1, 3))
    m = (dens >= 0.10).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (bw * bh / (hb * wb) >= MIN_AREA and bw >= 7 and bh >= 7 and area >= 0.15 * bw * bh):
            continue
        if x + bw >= wb - 1 and bw < 6:  # 오른쪽 끝의 좁은 띠(크롭 경계에 걸린 화면 요소)
            continue
        if x >= 0.86 * wb and y >= 0.84 * hb:  # 오른쪽 아래 구석으로 들어온 진행자 화면
            continue
        out.append((int(x * BLOCK), int(y * BLOCK), int((x + bw) * BLOCK), int((y + bh) * BLOCK)))
    return out


def classify(a: np.ndarray, title_box, body_boxes: list[list[int]], white_ratio: float | None = None) -> dict:
    h, w, _ = a.shape
    if white_ratio is None:
        white_ratio = float((a.astype(np.int16).mean(axis=2) >= 245).mean())
    if white_ratio < 0.35:
        return {"layout": "media", "graphics": [], "text_box": None}
    text = [tuple(b) for b in body_boxes if BODY_H[0] <= b[3] <= BODY_H[1]]
    boxes = list(text)
    if title_box:
        boxes.append((title_box[0], title_box[1], title_box[2] - title_box[0], title_box[3] - title_box[1]))
    g = graphics(a, boxes)
    tb = None
    if text:
        tb = (min(b[0] for b in text), min(b[1] for b in text), max(b[0] + b[2] for b in text), max(b[1] + b[3] for b in text))
    if not g:
        return {"layout": "text_only", "graphics": [], "text_box": tb}
    g.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    big = g[0]
    gx0, gy0, gx1, gy1 = min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])  # noqa: E731
    if tb is None or len(text) <= 1:
        lay = "image_pair" if len(g) >= 2 and area(g[1]) >= 0.5 * area(big) and (g[1][0] >= big[2] - 16 or g[1][2] <= big[0] + 16) else "image_full"
    else:
        tcx, gcx = (tb[0] + tb[2]) / 2, (big[0] + big[2]) / 2
        overlap_x = min(tb[2], gx1) - max(tb[0], gx0)
        if len(g) >= 2 and area(g[1]) >= 0.5 * area(big) and (g[1][0] >= big[2] - 16 or g[1][2] <= big[0] + 16) and abs(g[1][1] - big[1]) < 0.25 * h:
            lay = "image_pair"
        elif (gy1 <= tb[1] + 12 or gy0 >= tb[3] - 12) and overlap_x > 0:
            lay = "image_stack"  # 그림과 글이 세로로 완전히 갈리고 가로로 겹침 — 좌우 판정보다 먼저 본다
        elif big[2] <= tb[0] + 24 or gcx < tcx - 0.12 * w:
            lay = "image_left"
        elif big[0] >= tb[2] - 24 or gcx > tcx + 0.12 * w:
            lay = "image_right"
        elif overlap_x > 0.5 * (tb[2] - tb[0]):
            lay = "image_stack"
        else:
            lay = "image_left" if gcx < tcx else "image_right"
    return {"layout": lay, "graphics": g, "text_box": tb}
