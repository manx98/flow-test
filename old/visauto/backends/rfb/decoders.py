"""RFB 矩形解码器：Raw / CopyRect / Hextile / ZRLE / Tight。

约定（由 SetPixelFormat 固定）：
- PIXEL  = 4 字节、小端、true-colour，红移16/绿移8/蓝移0 → 字节序为 [B, G, R, x]。
- CPIXEL (ZRLE) = PIXEL 的 3 个有效字节、同 PIXEL 字节序 → [B, G, R]。
- TPIXEL (Tight)= 红、绿、蓝 三字节（RFB 规定该顺序）→ [R, G, B]，需反转成 BGR。

framebuffer fb 为 numpy (H, W, 3) uint8，BGR。所有函数写入 fb[y:y+h, x:x+w]。
encoding 编号：Raw=0 CopyRect=1 Hextile=5 Tight=7 ZRLE=16 DesktopSize(伪)=-223。
"""
from __future__ import annotations

import struct
import zlib
from io import BytesIO

import numpy as np

ENC_RAW = 0
ENC_COPYRECT = 1
ENC_HEXTILE = 5
ENC_TIGHT = 7
ENC_ZRLE = 16
ENC_DESKTOP_SIZE = -223

BYTES_PER_PIXEL = 4


class DecoderState:
    """跨矩形/跨帧持有的解码状态（zlib 流必须持久）。"""

    def __init__(self):
        self.zrle = zlib.decompressobj()
        self.tight = [None, None, None, None]  # 4 路 Tight zlib 流，按需创建/重置

    def reset_tight_stream(self, i: int) -> None:
        self.tight[i] = zlib.decompressobj()


class _BytesReader:
    """对内存 bytes 的顺序读取器（供已解压数据使用）。"""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n: int) -> bytes:
        end = self._pos + n
        if end > len(self._data):
            raise ValueError("RFB 数据流读越界（解压数据不足）")
        out = self._data[self._pos:end]
        self._pos = end
        return out

    def remaining(self) -> int:
        return len(self._data) - self._pos


# ---------------------------------------------------------------------------
# 像素读取
# ---------------------------------------------------------------------------
def _read_pixel32(read) -> np.ndarray:
    """读 4 字节 PIXEL，返回 [B, G, R]。"""
    b = read(4)
    return np.array((b[0], b[1], b[2]), dtype=np.uint8)


def _read_cpixel(reader: _BytesReader) -> np.ndarray:
    """ZRLE CPIXEL：3 字节 [B, G, R]。"""
    b = reader.read(3)
    return np.array((b[0], b[1], b[2]), dtype=np.uint8)


def _read_tpixel(read) -> np.ndarray:
    """Tight TPIXEL：3 字节 [R, G, B] → 返回 BGR。"""
    b = read(3)
    return np.array((b[2], b[1], b[0]), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Raw / CopyRect
# ---------------------------------------------------------------------------
def decode_raw(read, fb, x, y, w, h, state=None):
    data = read(w * h * BYTES_PER_PIXEL)
    arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)[:, :, :3]
    fb[y:y + h, x:x + w] = arr


def decode_copyrect(read, fb, x, y, w, h, state=None):
    sx, sy = struct.unpack(">HH", read(4))
    # 先拷贝源区域，避免源/目标重叠时被覆盖。
    fb[y:y + h, x:x + w] = fb[sy:sy + h, sx:sx + w].copy()


# ---------------------------------------------------------------------------
# Hextile（16x16 瓦片）
# ---------------------------------------------------------------------------
_HEX_RAW = 1
_HEX_BG = 2
_HEX_FG = 4
_HEX_ANY = 8
_HEX_COLOURED = 16


def decode_hextile(read, fb, x, y, w, h, state=None):
    bg = np.zeros(3, dtype=np.uint8)
    fg = np.zeros(3, dtype=np.uint8)
    for ty in range(0, h, 16):
        th = min(16, h - ty)
        for tx in range(0, w, 16):
            tw = min(16, w - tx)
            subenc = read(1)[0]
            ox, oy = x + tx, y + ty
            if subenc & _HEX_RAW:
                data = read(tw * th * BYTES_PER_PIXEL)
                tile = np.frombuffer(data, np.uint8).reshape(th, tw, 4)[:, :, :3]
                fb[oy:oy + th, ox:ox + tw] = tile
                continue
            if subenc & _HEX_BG:
                bg = _read_pixel32(read)
            if subenc & _HEX_FG:
                fg = _read_pixel32(read)
            fb[oy:oy + th, ox:ox + tw] = bg
            if subenc & _HEX_ANY:
                nsub = read(1)[0]
                coloured = subenc & _HEX_COLOURED
                for _ in range(nsub):
                    color = _read_pixel32(read) if coloured else fg
                    xy = read(1)[0]
                    wh = read(1)[0]
                    sx = xy >> 4
                    sy = xy & 0x0F
                    sw = (wh >> 4) + 1
                    sh = (wh & 0x0F) + 1
                    fb[oy + sy:oy + sy + sh, ox + sx:ox + sx + sw] = color


# ---------------------------------------------------------------------------
# ZRLE（64x64 瓦片，持久 zlib 流）
# ---------------------------------------------------------------------------
def decode_zrle(read, fb, x, y, w, h, state: DecoderState):
    length = struct.unpack(">I", read(4))[0]
    comp = read(length)
    data = state.zrle.decompress(comp)
    reader = _BytesReader(data)
    for ty in range(0, h, 64):
        th = min(64, h - ty)
        for tx in range(0, w, 64):
            tw = min(64, w - tx)
            tile = _zrle_tile(reader, tw, th)
            fb[y + ty:y + ty + th, x + tx:x + tx + tw] = tile


def _zrle_runlen(reader: _BytesReader) -> int:
    length = 1
    while True:
        b = reader.read(1)[0]
        length += b
        if b != 255:
            return length


def _zrle_tile(reader: _BytesReader, tw: int, th: int) -> np.ndarray:
    subenc = reader.read(1)[0]
    n = tw * th

    # 原始
    if subenc == 0:
        out = np.empty((n, 3), np.uint8)
        for i in range(n):
            out[i] = _read_cpixel(reader)
        return out.reshape(th, tw, 3)

    # 单色
    if subenc == 1:
        return np.tile(_read_cpixel(reader), (th, tw, 1))

    # 打包调色板（2..16 色）
    if 2 <= subenc <= 16:
        palette = np.array([_read_cpixel(reader) for _ in range(subenc)], np.uint8)
        bits = 1 if subenc <= 2 else (2 if subenc <= 4 else 4)
        return _zrle_packed_palette(reader, palette, tw, th, bits)

    # 纯 RLE
    if subenc == 128:
        out = np.empty((n, 3), np.uint8)
        idx = 0
        while idx < n:
            color = _read_cpixel(reader)
            run = _zrle_runlen(reader)
            out[idx:idx + run] = color
            idx += run
        return out.reshape(th, tw, 3)

    # 调色板 RLE（130..255）
    if subenc >= 130:
        psize = subenc - 128
        palette = np.array([_read_cpixel(reader) for _ in range(psize)], np.uint8)
        out = np.empty((n, 3), np.uint8)
        idx = 0
        while idx < n:
            b = reader.read(1)[0]
            if b < 128:
                out[idx] = palette[b]
                idx += 1
            else:
                run = _zrle_runlen(reader)
                out[idx:idx + run] = palette[b - 128]
                idx += run
        return out.reshape(th, tw, 3)

    raise ValueError(f"未知 ZRLE 子编码：{subenc}")


def _zrle_packed_palette(reader, palette, tw, th, bits) -> np.ndarray:
    mask = (1 << bits) - 1
    out = np.empty((th, tw, 3), np.uint8)
    row_bytes = (tw * bits + 7) // 8
    for row in range(th):
        rb = reader.read(row_bytes)
        bitbuf = 0
        bitcnt = 0
        bi = 0
        for col in range(tw):
            if bitcnt < bits:
                bitbuf = (bitbuf << 8) | rb[bi]
                bi += 1
                bitcnt += 8
            bitcnt -= bits
            out[row, col] = palette[(bitbuf >> bitcnt) & mask]
    return out


# ---------------------------------------------------------------------------
# Tight
# ---------------------------------------------------------------------------
def _read_compact_len(read) -> int:
    b = read(1)[0]
    length = b & 0x7F
    if b & 0x80:
        b = read(1)[0]
        length |= (b & 0x7F) << 7
        if b & 0x80:
            b = read(1)[0]
            length |= (b & 0xFF) << 14
    return length


def decode_tight(read, fb, x, y, w, h, state: DecoderState):
    control = read(1)[0]
    # 低 4 位：复位对应 zlib 流
    for i in range(4):
        if control & (1 << i):
            state.reset_tight_stream(i)

    op = control >> 4
    if op == 0x08:  # Fill
        color = _read_tpixel(read)
        fb[y:y + h, x:x + w] = color
        return
    if op == 0x09:  # JPEG
        length = _read_compact_len(read)
        jpeg = read(length)
        from PIL import Image as PILImage
        img = PILImage.open(BytesIO(jpeg)).convert("RGB")
        arr = np.asarray(img)[:, :, ::-1]  # RGB → BGR
        fb[y:y + h, x:x + w] = arr
        return
    if op >= 0x08:
        raise ValueError(f"未知 Tight 压缩类型：{op:#x}")

    # —— 基本压缩 ——
    stream_id = (control >> 4) & 0x03
    filter_id = 0
    if control & 0x40:
        filter_id = read(1)[0]

    if filter_id == 0:        # copy
        tile = _tight_read_data(read, state, stream_id, w * h * 3, w, h, "copy")
        fb[y:y + h, x:x + w] = tile
    elif filter_id == 1:      # palette
        num = read(1)[0] + 1
        palette = np.array([_read_tpixel(read) for _ in range(num)], np.uint8)
        if num <= 2:
            row_bytes = (w + 7) // 8
            raw = _tight_read_raw(read, state, stream_id, row_bytes * h)
            tile = _tight_palette_1bit(raw, palette, w, h)
        else:
            raw = _tight_read_raw(read, state, stream_id, w * h)
            idx = np.frombuffer(raw, np.uint8).reshape(h, w)
            tile = palette[idx]
        fb[y:y + h, x:x + w] = tile
    elif filter_id == 2:      # gradient
        raw = _tight_read_raw(read, state, stream_id, w * h * 3)
        tile = _tight_gradient(raw, w, h)
        fb[y:y + h, x:x + w] = tile
    else:
        raise ValueError(f"未知 Tight 过滤器：{filter_id}")


def _tight_read_raw(read, state: DecoderState, stream_id: int, expected: int) -> bytes:
    """读 Tight 基本压缩数据：小于 12 字节不压缩，否则经对应 zlib 流解压。"""
    if expected < 12:
        return read(expected)
    length = _read_compact_len(read)
    cdata = read(length)
    if state.tight[stream_id] is None:
        state.reset_tight_stream(stream_id)
    return state.tight[stream_id].decompress(cdata)


def _tight_read_data(read, state, stream_id, expected, w, h, kind):
    raw = _tight_read_raw(read, state, stream_id, expected)
    if kind == "copy":
        arr = np.frombuffer(raw, np.uint8).reshape(h, w, 3)[:, :, ::-1]  # RGB→BGR
        return np.ascontiguousarray(arr)
    raise ValueError(kind)


def _tight_palette_1bit(raw: bytes, palette: np.ndarray, w: int, h: int) -> np.ndarray:
    row_bytes = (w + 7) // 8
    out = np.empty((h, w, 3), np.uint8)
    for row in range(h):
        base = row * row_bytes
        for col in range(w):
            byte = raw[base + (col >> 3)]
            bit = (byte >> (7 - (col & 7))) & 1
            out[row, col] = palette[bit]
    return out


def _tight_gradient(raw: bytes, w: int, h: int) -> np.ndarray:
    """Tight 梯度过滤反演（按 R,G,B 通道做 left+up-upleft 预测）。"""
    res = np.frombuffer(raw, np.uint8).astype(np.int32).reshape(h, w, 3)  # 残差 R,G,B
    out = np.zeros((h, w, 3), np.int32)
    for row in range(h):
        for col in range(w):
            left = out[row, col - 1] if col > 0 else 0
            up = out[row - 1, col] if row > 0 else 0
            upleft = out[row - 1, col - 1] if (row > 0 and col > 0) else 0
            pred = left + up - upleft
            pred = np.clip(pred, 0, 255)
            out[row, col] = (res[row, col] + pred) & 0xFF
    rgb = out.astype(np.uint8)
    return np.ascontiguousarray(rgb[:, :, ::-1])  # RGB→BGR


# ---------------------------------------------------------------------------
# 调度表
# ---------------------------------------------------------------------------
DECODERS = {
    ENC_RAW: decode_raw,
    ENC_COPYRECT: decode_copyrect,
    ENC_HEXTILE: decode_hextile,
    ENC_ZRLE: decode_zrle,
    ENC_TIGHT: decode_tight,
}
