"""VNC 密码认证（DES）。

VNC Authentication：服务器发 16 字节 challenge，客户端用“位反转后的密码”作
DES 密钥，对 challenge 两个 8 字节块做 ECB 加密，回送 16 字节 response。

DES 不在标准库，这里用 cryptography 的 TripleDES（K1=K2=K3 等价单 DES）实现，
惰性导入；未安装时给清晰报错。
"""
from __future__ import annotations

from ...exceptions import BackendError


def _reverse_bits(byte: int) -> int:
    """反转一个字节的位序（VNC DES 密钥的特殊处理）。"""
    result = 0
    for i in range(8):
        if byte & (1 << i):
            result |= 1 << (7 - i)
    return result


def _make_key(password: str) -> bytes:
    pw = password.encode("latin-1", "replace")[:8]
    pw = pw + b"\x00" * (8 - len(pw))
    return bytes(_reverse_bits(b) for b in pw)


def vnc_auth_response(password: str, challenge: bytes) -> bytes:
    """计算 16 字节认证响应。"""
    if len(challenge) != 16:
        raise BackendError(f"VNC challenge 长度异常：{len(challenge)}")
    key = _make_key(password)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:
        raise BackendError(
            "VNC 密码认证需要 cryptography：pip install cryptography"
        ) from e
    # TripleDES 用 24 字节密钥，K1=K2=K3 时等价于单 DES。
    cipher = Cipher(algorithms.TripleDES(key * 3), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(challenge) + enc.finalize()
