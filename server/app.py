"""FastAPI 入口：工程/图 REST + 静态前端 + (后续) WebRTC/WS 路由。"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .models import CompleteReq, CreateProject, FlowGraph, Meta, RenameImage
from .project import Project, list_projects

app = FastAPI(title="flow-test 测试工作流服务端")

# 开发期前端在独立端口(vite)，放开 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.on_event("shutdown")
async def _shutdown():
    try:
        from .webrtc import close_all_pcs
        await close_all_pcs()
    except Exception:
        pass
    try:
        from .devices import sessions
        sessions.close_all()
    except Exception:
        pass


# ======================= 工程 =======================
@app.get("/api/projects")
def api_list_projects():
    return {"projects": list_projects()}


@app.post("/api/projects")
def api_create_project(body: CreateProject):
    p = Project(body.name)
    if p.exists:
        raise HTTPException(409, "工程已存在")
    p.ensure()
    return {"name": p.name}


def _require(name: str) -> Project:
    p = Project(name)
    if not p.exists:
        raise HTTPException(404, "工程不存在")
    return p


@app.delete("/api/projects/{name}")
def api_delete_project(name: str):
    _require(name).delete()
    return {"ok": True}


@app.get("/api/projects/{name}/flow")
def api_get_flow(name: str):
    p = _require(name)
    p.register_imagepath()
    return {"graph": p.load_flow()}


@app.put("/api/projects/{name}/flow")
def api_put_flow(name: str, body: FlowGraph):
    _require(name).save_flow(body.graph)
    return {"ok": True}


@app.get("/api/projects/{name}/meta")
def api_get_meta(name: str):
    return {"meta": _require(name).load_meta()}


@app.put("/api/projects/{name}/meta")
def api_put_meta(name: str, body: Meta):
    _require(name).save_meta(body.meta)
    return {"ok": True}


# ======================= 图片 =======================
@app.get("/api/projects/{name}/images")
def api_list_images(name: str):
    return {"images": _require(name).list_images()}


@app.post("/api/projects/{name}/images")
async def api_upload_image(name: str, file: UploadFile):
    p = _require(name)
    os.makedirs(p.images_dir, exist_ok=True)
    dest = p.image_path(file.filename or "image.png")
    with open(dest, "wb") as f:
        f.write(await file.read())
    return {"name": os.path.basename(dest)}


@app.post("/api/projects/{name}/images/{img}/rename")
def api_rename_image(name: str, img: str, body: RenameImage):
    p = _require(name)
    try:
        return {"name": p.rename_image(img, body.name)}
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{name}/images/{img}")
def api_get_image(name: str, img: str):
    p = _require(name)
    path = p.image_path(img)
    if not os.path.exists(path):
        raise HTTPException(404, "图片不存在")
    return FileResponse(path)


# ======================= 运行结果（报告/证据）=======================
@app.get("/api/projects/{name}/results")
def api_list_results(name: str):
    return {"runs": _require(name).list_runs()}


@app.delete("/api/projects/{name}/results")
def api_clear_results(name: str):
    return {"deleted": _require(name).clear_runs()}


@app.delete("/api/projects/{name}/results/{run}")
def api_delete_result(name: str, run: str):
    p = _require(name)
    try:
        p.delete_run(run)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@app.get("/api/projects/{name}/results/{run}/{fname}")
def api_get_result(name: str, run: str, fname: str):
    p = _require(name)
    path = p.result_file(run, fname)
    if not os.path.exists(path):
        raise HTTPException(404, "结果文件不存在")
    return FileResponse(path)


# ======================= 脚本代码补全（jedi）=======================
@app.post("/api/complete")
def api_complete(body: CompleteReq):
    from .complete import complete
    try:
        return {"completions": complete(body.code, body.line, body.column)}
    except ImportError:
        raise HTTPException(503, "代码补全需要 jedi：pip install jedi")


# ======================= 节点目录（前端建面板用）=======================
@app.get("/api/nodes")
def api_node_catalog():
    from .flow.catalog import node_catalog
    return JSONResponse(node_catalog())


# ======================= WebRTC / WS（M2/M3）=======================
def _mount_realtime():
    try:
        from .signaling import router as ws_router
        app.include_router(ws_router)
    except Exception as e:  # 实时模块未就绪时不影响 REST
        print(f"[warn] 实时模块未挂载：{e}")


_mount_realtime()


# ======================= 静态前端 =======================
_WEB_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_WEB_DIST):
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")


def main():
    import uvicorn
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
