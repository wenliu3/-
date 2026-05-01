"""
紊流番剧 v6 - AGE动漫真实数据源
详情页：左侧播放器 + 右侧选集
"""
import json, sys, webbrowser, threading, socket, re, subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
STATIC = BASE / "static"
AGE = "https://www.agedm.io"
CDN = "https://cdn.aqdstatic.com:966/age"

app = FastAPI(title="wenliu", version="6.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

pool = ThreadPoolExecutor(max_workers=8)
_cache = {"home": None, "detail": {}, "play": {}}


def _curl(url, timeout=15):
    cmd = ["curl.exe", "-s", "-L", "--max-time", str(timeout),
           "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
           url]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    return r.stdout.decode("utf-8")


def fetch_homepage():
    if _cache["home"]:
        return _cache["home"]
    html = _curl(AGE)
    if not html:
        return []
    items = []
    seen = set()
    for m in re.finditer(r'href="(http://www\.agedm\.io/detail/(\d+))"', html):
        url, aid = m.groups()
        if aid in seen:
            continue
        seen.add(aid)
        items.append({"id": aid, "cover": f"/api/ageimg/{aid}"})
    # Fetch titles in parallel
    def get_title(item):
        detail = fetch_detail(item["id"])
        if detail:
            item["title"] = detail.get("title", "")
            item["tags"] = detail.get("tags", [])
            item["status"] = detail.get("status", "")
            item["desc"] = detail.get("desc", "")
            item["episodes"] = detail.get("episode_count", 0)
        return item
    with pool:
        results = list(pool.map(get_title, items))
    _cache["home"] = results
    return results


def fetch_detail(age_id):
    if age_id in _cache["detail"]:
        return _cache["detail"][age_id]
    html = _curl(f"{AGE}/detail/{age_id}")
    if not html or len(html) < 500:
        return None
    info = {"id": age_id}
    m = re.search(r"<title>([^<]+)</title>", html)
    if m:
        t = m.group(1).strip()
        t = re.sub(r"\s*-\s*AGE动漫.*$", "", t)
        if t:
            info["title"] = t
    m = re.search(r'property="og:description"[^>]+content="([^"]+)"', html)
    if m:
        info["desc"] = m.group(1).strip()[:300]
    tags = re.findall(r'href="/catalog/[^"]*"[^>]*>([^<]+)', html)
    info["tags"] = [t.strip() for t in tags if t.strip() and len(t.strip()) > 1 and "全部" not in t][:8]
    info["status"] = "完结" if "完结" in html else "连载"
    year_m = re.search(r'(\d{4})', info.get("title", ""))
    if year_m:
        info["year"] = int(year_m.group(1))
    # Play links with titles
    play_blocks = re.findall(r'href="(/play/[^"]+)"[^>]*>([^<]+)', html)
    play_links = []
    eps = []
    seen = set()
    for path, title in play_blocks:
        if path in seen:
            continue
        seen.add(path)
        play_links.append(path)
        t = title.strip()
        if not t or len(t) < 2:
            t = f"第{len(eps)+1}集"
        eps.append({"id": path, "i": len(eps) + 1, "t": t})
    info["play_links"] = play_links
    info["episodes"] = eps
    info["episode_count"] = len(play_links)
    _cache["detail"][age_id] = info
    return info


def fetch_play_iframe(play_path):
    if play_path in _cache["play"]:
        return _cache["play"][play_path]
    html = _curl(f"{AGE}{play_path}")
    if not html:
        return None
    m = re.search(r'<iframe[^>]+src="([^"]+)"', html)
    result = m.group(1) if m else None
    if result:
        _cache["play"][play_path] = result
    return result


# ===== API =====

@app.get("/api/search")
def api_search(q: str = Query(default=""), page: int = Query(default=1), limit: int = Query(default=50)):
    items = fetch_homepage()
    if q:
        html = _curl(f"{AGE}/search?query={q}")
        if html:
            seen = set()
            results = []
            for m in re.finditer(r'href="(http://www\.agedm\.io/detail/(\d+))"', html):
                url, aid = m.groups()
                if aid in seen:
                    continue
                seen.add(aid)
                results.append(aid)
            if results:
                # Get details
                detail_items = []
                for aid in results:
                    d = fetch_detail(aid)
                    if d:
                        detail_items.append({
                            "id": aid,
                            "title": d.get("title", ""),
                            "cover": f"/api/ageimg/{aid}",
                            "tags": d.get("tags", []),
                            "status": d.get("status", ""),
                            "episodes": d.get("episode_count", 0),
                            "desc": d.get("desc", ""),
                        })
                items = detail_items
    total = len(items)
    start = (page - 1) * limit
    return {"ok": True, "data": items[start:start + limit], "total": total, "page": page}


@app.get("/api/detail/{age_id}")
def api_detail(age_id: str):
    info = fetch_detail(age_id)
    if not info:
        return JSONResponse({"ok": False, "msg": "not found"}, status_code=404)
    eps = info.get("episodes", [])
    if not eps:
        play_links = info.get("play_links", [])
        eps = [{"id": pl, "i": i + 1, "t": f"第{i+1}集"} for i, pl in enumerate(play_links)]
    return {
        "ok": True,
        "data": {
            "id": age_id,
            "title": info.get("title", ""),
            "cover": f"/api/ageimg/{age_id}",
            "tags": info.get("tags", []),
            "status": info.get("status", ""),
            "desc": info.get("desc", ""),
            "episodes": eps,
        },
    }


@app.get("/api/play")
def api_play(ep: str = Query(...)):
    iframe = fetch_play_iframe(ep)
    if not iframe:
        return JSONResponse({"ok": False, "msg": "no video"}, status_code=404)
    return {"ok": True, "data": {"episode_id": ep, "iframe": iframe}}


@app.get("/api/recommend")
def api_recommend(aid: str = Query(default=None), limit: int = Query(default=12)):
    items = fetch_homepage()
    if aid:
        items = [x for x in items if x["id"] != aid]
    return {"ok": True, "data": items[:limit]}


@app.get("/api/ageimg/{age_id}")
def api_ageimg(age_id: str):
    url = f"{CDN}/{age_id}.jpg"
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "-L", "--max-time", "10", "-H", "User-Agent: Mozilla/5.0", url],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout and len(r.stdout) > 100:
            ct = "image/jpeg"
            if b"\x89PNG" in r.stdout[:4]:
                ct = "image/png"
            return Response(content=r.stdout, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})
    except:
        pass
    return JSONResponse({"error": "failed"}, status_code=502)


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


def find_free_port():
    for p in [18888, 19999, 18080, 17777, 9090]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", p))
                return p
            except OSError:
                continue
    return 0


if __name__ == "__main__":
    import uvicorn
    port = find_free_port()
    threading.Timer(2.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"\n  [WenLiu] http://localhost:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
