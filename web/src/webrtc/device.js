// 浏览器侧 WebRTC：连接设备 → 收视频轨 → DataChannel 发输入
import { api } from '../api.js'

export class DeviceConnection {
  constructor() {
    this.pc = null
    this.dc = null
    this.sessionId = null
    this.width = 0
    this.height = 0
    this.stream = null         // 收到的视频轨（MediaStream）
    this._videos = new Set()   // 显示此设备的 <video>（人机交互节点，可多个）
  }

  // 人机交互节点登记/注销一个 <video> 显示面；共享同一条轨。
  attachVideo(el) {
    this._videos.add(el)
    if (this.stream) { el.srcObject = this.stream; el.play?.().catch(() => {}) }
  }

  detachVideo(el) {
    this._videos.delete(el)
    try { el.srcObject = null } catch (_) {}
  }

  // 抓取当前帧到 canvas（设备原始分辨率）。复用已在播放的 <video>，否则临时建一个。
  async grabFrame() {
    if (!this.stream) throw new Error('无视频流')
    let v = [...this._videos].find(el => el.videoWidth > 0)
    let temp = null
    if (!v) {
      temp = document.createElement('video')
      temp.muted = true
      temp.srcObject = this.stream
      await temp.play().catch(() => {})
      if (!temp.videoWidth) await new Promise(r => { temp.onloadeddata = r })
      v = temp
    }
    const w = v.videoWidth || this.width
    const h = v.videoHeight || this.height
    const cvs = document.createElement('canvas')
    cvs.width = w; cvs.height = h
    cvs.getContext('2d').drawImage(v, 0, 0, w, h)
    if (temp) { try { temp.srcObject = null; temp.remove() } catch (_) {} }
    return cvs
  }

  // 抓当前帧并编码为 Blob（默认 PNG）。
  async grabBlob(type = 'image/png') {
    const cvs = await this.grabFrame()
    return await new Promise((res, rej) =>
      cvs.toBlob(b => b ? res(b) : rej(new Error('编码失败')), type))
  }

  async connect(kind, config, project, nodeId) {
    // 1) 服务端连接设备（带 project+node_id 以便运行时复用此连接）
    const dev = await api.connectDevice(kind, config, project, nodeId)
    this.sessionId = dev.session_id
    this.width = dev.width
    this.height = dev.height

    // 2) 建 PeerConnection
    const pc = new RTCPeerConnection()
    this.pc = pc
    pc.addTransceiver('video', { direction: 'recvonly' })
    this.dc = pc.createDataChannel('input')
    pc.ontrack = (e) => {
      this.stream = e.streams[0]
      for (const el of this._videos) {
        el.srcObject = this.stream
        el.play?.().catch(() => {})
      }
    }

    // 3) offer → 服务端 answer
    await pc.setLocalDescription(await pc.createOffer())
    await this._waitIce(pc)
    const ans = await api.webrtcOffer(this.sessionId, pc.localDescription.sdp, pc.localDescription.type)
    await pc.setRemoteDescription(ans)
    return dev
  }

  _waitIce(pc) {
    if (pc.iceGatheringState === 'complete') return Promise.resolve()
    return new Promise((resolve) => {
      const check = () => {
        if (pc.iceGatheringState === 'complete') {
          pc.removeEventListener('icegatheringstatechange', check)
          resolve()
        }
      }
      pc.addEventListener('icegatheringstatechange', check)
      setTimeout(resolve, 5000)
    })
  }

  send(evt) {
    if (this.dc && this.dc.readyState === 'open') this.dc.send(JSON.stringify(evt))
  }

  async close() {
    for (const el of this._videos) { try { el.srcObject = null } catch (_) {} }
    this._videos.clear()
    this.stream = null
    try { this.pc && this.pc.close() } catch (e) {}
    if (this.sessionId) { try { await api.disconnectDevice(this.sessionId) } catch (e) {} }
    this.pc = this.dc = this.sessionId = null
  }
}
