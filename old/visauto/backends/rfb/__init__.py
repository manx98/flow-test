"""RFB (Remote Framebuffer) over WebSocket 客户端实现，供 NoVNCBackend 使用。

子模块：
- transport : WSStream，把 websocket 二进制帧缓冲成可按字节读取的流
- auth      : VNC 密码（DES）认证
- keysym    : 键名/字符 → X11 keysym
- decoders  : Raw/CopyRect/Hextile/ZRLE/Tight 矩形解码
- protocol  : 握手 + FramebufferUpdate 状态机
"""
