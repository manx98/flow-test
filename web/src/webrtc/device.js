// 浏览器侧设备连接：优先 WebRTC DataChannel 收帧/发输入，必要时降级 HTTP 截图。
import { api } from '../api.js'

export class DeviceConnection {
  constructor() {
    this.pc = null
    this.dc = null
    this.sessionId = null
    this.width = 0
    this.height = 0
    this.stream = null         // 兼容原生视频轨（MediaStream）
    this._videos = new Set()   // 显示此设备的 <video> 容器（人机交互节点，可多个）
    this.mode = 'webrtc'
    this.captureUrl = ''
    this.inputUrl = ''
    this._captureTimer = null
    this._captureObjectURL = ''
    this._lastFrameBlob = null
    this._streamPromise = null
    this.onDisconnect = null
    this._closed = false
    this._disconnectNotified = false
  }

  // 人机交互节点登记/注销一个 <video> 显示面；共享同一设备连接。
  attachVideo(el) {
    this._videos.add(el)
    this.ensureStream().catch(() => {})
    if (this.mode === 'capture' || this.mode === 'webrtc-data') {
      el.style.backgroundSize = '100% 100%'
      el.style.backgroundPosition = 'center'
      if (this._captureObjectURL) el.style.backgroundImage = `url("${this._captureObjectURL}")`
      if (this.mode === 'capture') this._startCaptureLoop()
      return
    }
    if (this.stream) { el.srcObject = this.stream; el.play?.().catch(() => {}) }
  }

  detachVideo(el) {
    this._videos.delete(el)
    try { el.srcObject = null } catch (_) {}
    el.style.backgroundImage = ''
    if (!this._videos.size) this._stopStream()
  }

  // 抓取当前帧到 canvas（设备原始分辨率）。复用已在播放的 <video>，否则临时建一个。
  async grabFrame() {
    if (!this.stream && this.mode !== 'capture' && this.mode !== 'webrtc-data') await this.ensureStream()
    if (this.mode === 'capture') return await this._grabCaptureFrame()
    if (this.mode === 'webrtc-data') return await this._grabBlobFrame(this._lastFrameBlob, '无 WebRTC 帧')
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
    this.captureUrl = dev.capture_url || ''
    this.inputUrl = dev.input_url || ''
    if (dev.stream_mode === 'capture') this.mode = 'capture'
    this._closed = false
    this._disconnectNotified = false
    return dev
  }

  async ensureStream() {
    if (this.mode === 'capture') {
      this._startCaptureLoop()
      return
    }
    if (this.stream || this.pc) return
    if (this._streamPromise) return this._streamPromise
    if (!this.sessionId) throw new Error('设备未连接')
    this._streamPromise = this._startWebRTC()
      .catch((err) => { this._stopStream(); throw err })
      .finally(() => { this._streamPromise = null })
    return this._streamPromise
  }

  async _startWebRTC() {
    const pc = new RTCPeerConnection()
    this.pc = pc
    pc.onconnectionstatechange = () => {
      if (['disconnected', 'failed', 'closed'].includes(pc.connectionState)) this._markDisconnected()
    }
    pc.oniceconnectionstatechange = () => {
      if (['disconnected', 'failed', 'closed'].includes(pc.iceConnectionState)) this._markDisconnected()
    }
    pc.addTransceiver('video', { direction: 'recvonly' })
    this.dc = pc.createDataChannel('input')
    this.dc.binaryType = 'arraybuffer'
    this.dc.onmessage = (e) => this._handleDataFrame(e.data)
    this.dc.onclose = () => this._markDisconnected()
    pc.ontrack = (e) => {
      this.stream = e.streams[0]
      for (const track of this.stream.getTracks?.() || []) {
        track.onended = () => this._markDisconnected()
        track.onmute = () => this._markDisconnected()
      }
      for (const el of this._videos) {
        el.srcObject = this.stream
        el.play?.().catch(() => {})
      }
    }

    // 3) offer → 服务端 answer
    await pc.setLocalDescription(await pc.createOffer())
    await this._waitIce(pc)
    const ans = await api.webrtcOffer(this.sessionId, pc.localDescription.sdp, pc.localDescription.type)
    if (ans.mode === 'capture') {
      this.mode = 'capture'
      this.captureUrl = ans.capture_url
      this.inputUrl = ans.input_url
      try { pc.close() } catch (_) {}
      this.pc = null
      this.dc = null
      this._startCaptureLoop()
      return
    }
    if (ans.mode === 'webrtc-video') this.mode = 'webrtc'
    if (ans.mode === 'webrtc-data') this.mode = 'webrtc-data'
    await pc.setRemoteDescription({ type: ans.type, sdp: ans.sdp })
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
    if (this.mode === 'capture' && this.inputUrl) {
      api.deviceInput(this.sessionId, evt).catch(() => {})
      return
    }
    if (this.dc && this.dc.readyState === 'open') {
      this.dc.send(JSON.stringify(evt))
      return
    }
    if (this.inputUrl) api.deviceInput(this.sessionId, evt).catch(() => {})
  }

  async close() {
    this._closed = true
    for (const el of this._videos) {
      try { el.srcObject = null } catch (_) {}
      el.style.backgroundImage = ''
    }
    this._videos.clear()
    this.stream = null
    if (this._captureTimer) clearInterval(this._captureTimer)
    this._captureTimer = null
    if (this._captureObjectURL) URL.revokeObjectURL(this._captureObjectURL)
    this._captureObjectURL = ''
    this._lastFrameBlob = null
    this._stopStream()
    if (this.sessionId) { try { await api.disconnectDevice(this.sessionId) } catch (e) {} }
    this.pc = this.dc = this.sessionId = null
    this.mode = 'webrtc'
    this.captureUrl = ''
    this.inputUrl = ''
  }

  _stopStream() {
    if (this._captureTimer) clearInterval(this._captureTimer)
    this._captureTimer = null
    try { this.stream?.getTracks?.().forEach(t => t.stop()) } catch (_) {}
    try { this.pc && this.pc.close() } catch (e) {}
    this.pc = null
    this.dc = null
    this.stream = null
    if (this.mode === 'webrtc-data') this.mode = 'webrtc'
  }

  _markDisconnected() {
    if (this._closed || this._disconnectNotified) return
    this._disconnectNotified = true
    for (const el of this._videos) {
      try { el.srcObject = null } catch (_) {}
      el.style.backgroundImage = ''
    }
    if (this._captureObjectURL) URL.revokeObjectURL(this._captureObjectURL)
    this._captureObjectURL = ''
    this._lastFrameBlob = null
    this._stopStream()
    this.onDisconnect?.()
  }

  _startCaptureLoop() {
    if (!this.captureUrl || this._captureTimer) return
    const tick = async () => {
      if (!this.captureUrl || this._videos.size === 0) return
      try {
        const r = await fetch(`${this.captureUrl}?t=${Date.now()}`, { cache: 'no-store' })
        if (!r.ok) { this._markDisconnected(); return }
        const blob = await r.blob()
        const nextURL = URL.createObjectURL(blob)
        const prevURL = this._captureObjectURL
        this._captureObjectURL = nextURL
        for (const el of this._videos) el.style.backgroundImage = `url("${nextURL}")`
        if (prevURL) URL.revokeObjectURL(prevURL)
      } catch (_) { this._markDisconnected() }
    }
    tick()
    this._captureTimer = setInterval(tick, 500)
  }

  async _grabCaptureFrame() {
    if (!this.captureUrl) throw new Error('无截图流')
    const r = await fetch(`${this.captureUrl}?t=${Date.now()}`, { cache: 'no-store' })
    if (!r.ok) throw new Error(await r.text() || r.status)
    const blob = await r.blob()
    return await this._grabBlobFrame(blob, '截图加载失败')
  }

  _handleDataFrame(data) {
    const blob = data instanceof Blob ? data : new Blob([data], { type: 'image/jpeg' })
    this._lastFrameBlob = blob
    const nextURL = URL.createObjectURL(blob)
    const prevURL = this._captureObjectURL
    this._captureObjectURL = nextURL
    for (const el of this._videos) {
      el.style.backgroundSize = '100% 100%'
      el.style.backgroundPosition = 'center'
      el.style.backgroundImage = `url("${nextURL}")`
    }
    if (prevURL) URL.revokeObjectURL(prevURL)
  }

  async _grabBlobFrame(blob, loadError) {
    if (!blob) throw new Error(loadError)
    const img = await new Promise((resolve, reject) => {
      const image = new Image()
      const url = URL.createObjectURL(blob)
      image.onload = () => { URL.revokeObjectURL(url); resolve(image) }
      image.onerror = () => { URL.revokeObjectURL(url); reject(new Error(loadError)) }
      image.src = url
    })
    const cvs = document.createElement('canvas')
    cvs.width = img.naturalWidth || this.width
    cvs.height = img.naturalHeight || this.height
    cvs.getContext('2d').drawImage(img, 0, 0, cvs.width, cvs.height)
    return cvs
  }
}
