#!/usr/bin/env python3
"""
FastAPI + Plotly dashboard for unified asset DB.

Serves:
  - REST API at /api/*
  - Static dashboard SPA at /
  - Image files via /media/<path> (maps to repo-root relative paths)

Usage:
  cd tools/dashboard_api && uvicorn main:app --reload --port 8017
  # or from repo root:
  uvicorn tools.dashboard_api.main:app --reload --port 8017
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "assets.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"
MEDIA_ROOT = REPO_ROOT / "data"

app = FastAPI(title="Asset Dashboard API")

# ── DB helpers ───────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def rowdicts(cursor_or_rows):
    if hasattr(cursor_or_rows, 'description'):
        cursor = cursor_or_rows
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    else:
        # already fetched list of sqlite3.Row
        rows = cursor_or_rows
        if not rows:
            return []
        cols = rows[0].keys()
        return [dict(zip(cols, row)) for row in rows]


# ── Static SPA ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def spa_root():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ── Media proxy ──────────────────────────────────────────

@app.get("/media/{path:path}")
def media_proxy(path: str):
    """Serve image/video files under data/ via /media/ prefix."""
    target = MEDIA_ROOT / path
    # Security: restrict to MEDIA_ROOT
    try:
        target.resolve().relative_to(MEDIA_ROOT.resolve())
    except ValueError:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if target.exists() and target.is_file():
        return FileResponse(target)
    return JSONResponse({"error": "not found"}, status_code=404)


# ── API ──────────────────────────────────────────────────

@app.get("/api/projects")
def list_projects():
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, label, description FROM projects ORDER BY id").fetchall()
        return {"projects": rowdicts(rows)}


@app.get("/api/projects/{project_id}/summary")
def project_summary(project_id: int):
    with get_db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not proj:
            return JSONResponse({"error": "not found"}, status_code=404)

        stats = conn.execute(
            "SELECT * FROM v_frame_summary WHERE project_id=?", (project_id,)
        ).fetchone()

        videos = []
        if project_id == 2:  # shishi
            videos = rowdicts(conn.execute("SELECT * FROM videos ORDER BY id").fetchall())

        return {
            "project": dict(proj),
            "stats": dict(stats) if stats else None,
            "videos": videos,
        }


@app.get("/api/projects/{project_id}/frames")
def list_frames(
    project_id: int,
    video_id: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(48, ge=1, le=200),
    q: str = Query(None),
    has_caption: bool = Query(None),
):
    with get_db() as conn:
        where = ["f.project_id = ?"]
        params = [project_id]
        if video_id:
            where.append("f.video_id = ?")
            params.append(video_id)
        if q:
            where.append("(f.filename LIKE ? OR f.caption_text LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if has_caption is not None:
            where.append("f.has_caption = ?")
            params.append(has_caption)

        where_sql = " AND ".join(where) if where else "1=1"

        count = conn.execute(
            f"SELECT COUNT(*) FROM frames f WHERE {where_sql}", params
        ).fetchone()[0]

        offset = (page - 1) * limit
        rows = conn.execute(f"""
            SELECT f.*,
                   v.subject, v.category, v.training_suitability, v.notes as vlm_notes
            FROM frames f
            LEFT JOIN vlm_reviews v ON f.id = v.frame_id
            WHERE {where_sql}
            ORDER BY f.id
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        return {
            "total": count,
            "page": page,
            "limit": limit,
            "pages": (count + limit - 1) // limit,
            "frames": rowdicts(rows),
        }


@app.get("/api/projects/{project_id}/vlm/distribution")
def vlm_distribution(project_id: int):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT training_suitability, count FROM v_score_distribution WHERE project_id=?",
            (project_id,),
        ).fetchall()
        return {"distribution": rowdicts(rows)}


@app.get("/api/projects/{project_id}/vlm/categories")
def vlm_categories(project_id: int):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT category, count FROM v_category_distribution WHERE project_id=?",
            (project_id,),
        ).fetchall()
        return {"categories": rowdicts(rows)}


@app.get("/api/projects/{project_id}/vlm/score-axes")
def vlm_score_axes(project_id: int):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT s.axis, ROUND(AVG(s.score), 2) as avg_score, COUNT(*) as count
            FROM vlm_scores s
            JOIN vlm_reviews vr ON s.review_id = vr.id
            JOIN frames f ON vr.frame_id = f.id
            WHERE f.project_id = ?
            GROUP BY s.axis
        """, (project_id,)).fetchall()
        return {"axes": rowdicts(rows)}


@app.get("/api/frames/{frame_id}/vlm")
def frame_vlm(frame_id: int):
    with get_db() as conn:
        review = conn.execute(
            "SELECT * FROM vlm_reviews WHERE frame_id=?", (frame_id,)
        ).fetchone()
        if not review:
            return JSONResponse({"error": "not found"}, status_code=404)
        scores = conn.execute(
            "SELECT axis, score FROM vlm_scores WHERE review_id=?", (review["id"],)
        ).fetchall()
        return {
            "review": dict(review),
            "scores": {r["axis"]: r["score"] for r in scores},
        }


# ── Run ──────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8017, reload=True)
