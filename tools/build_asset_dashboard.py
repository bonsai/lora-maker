#!/usr/bin/env python3
"""
Build local asset dashboard HTML for data/shishi.

Reads:
  - data/shishi/metadata/frame_manifest.json

Outputs:
  - data/shishi/review/asset-dashboard.html (standalone, file:// compatible)

Usage:
  python tools/build_asset_dashboard.py \
    --manifest data/shishi/metadata/frame_manifest.json \
    --output data/shishi/review/asset-dashboard.html
"""
import argparse
import json
import html as html_module
from pathlib import Path


HTML_TEMPLATE = r'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shishi Asset Dashboard — ローカル資産管理</title>
<style>
:root {
  --bg:#0f1116; --card:#181b23; --line:#2a2f3a; --fg:#e8eaf0;
  --dim:#9aa3b2; --accent:#ff5d8f; --ok:#39d98a; --warn:#ffd166;
  --info:#7cc4ff; --danger:#ff6b6b;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; padding-bottom:120px; }
header { position:sticky; top:0; z-index:10; background:rgba(15,17,22,.96); border-bottom:1px solid var(--line); padding:12px 16px; backdrop-filter:blur(8px); }
h1 { font-size:16px; margin:0 0 3px; }
.sub { color:var(--dim); font-size:11px; }
.stats { display:flex; gap:12px; flex-wrap:wrap; margin-top:8px; font-size:12px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:4px 10px; }
.stat b { color:var(--ok); }
.controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:10px; }
button, input, select { font:inherit; color:var(--fg); background:var(--card); border:1px solid var(--line); border-radius:6px; padding:4px 10px; cursor:pointer; font-size:12px; }
button.active { border-color:var(--accent); color:var(--accent); }
input[type=search] { min-width:180px; cursor:text; }
.view-group { display:flex; gap:3px; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:3px; }
.view-group button { border:none; background:transparent; padding:4px 10px; border-radius:4px; }
.view-group button.active { background:var(--accent); color:#fff; }
main { padding:14px 16px; }
/* Video Gallery */
.gallery { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
.vcard { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }
.vcard.picked { border-color:var(--ok); }
.vthumb { position:relative; aspect-ratio:16/9; background:#000; }
.vthumb img { width:100%; height:100%; object-fit:cover; display:block; }
.vinfo { padding:10px 12px; display:flex; flex-direction:column; gap:5px; }
.vtitle { font-size:12px; font-weight:600; line-height:1.3; }
.vmeta { color:var(--dim); font-size:11px; display:flex; gap:8px; flex-wrap:wrap; }
.badge { border:1px solid var(--line); border-radius:999px; padding:0 7px; font-size:11px; }
.badge.approved { color:var(--ok); border-color:#2a5a3a; }
.badge.pending { color:var(--warn); border-color:#5a4a1d; }
.badge.error { color:var(--danger); border-color:#5a1d1d; }
.vactions { display:flex; gap:6px; margin-top:4px; }
.vactions button { padding:3px 8px; font-size:11px; }
/* Frame Grid */
.fgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; }
.fcard { background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.fcard img { width:100%; aspect-ratio:16/9; object-fit:cover; display:block; background:#000; }
.fmeta { padding:6px 8px; font-size:11px; color:var(--dim); }
.fmeta .fcap { color:var(--fg); font-size:10px; line-height:1.3; margin-top:3px; word-break:break-all; }
/* Dataset Table */
.dtable { width:100%; border-collapse:collapse; font-size:11px; }
.dtable th, .dtable td { border:1px solid var(--line); padding:5px 8px; text-align:left; }
.dtable th { background:var(--card); color:var(--dim); font-weight:500; position:sticky; top:0; }
.dtable td img { width:80px; height:45px; object-fit:cover; border-radius:4px; display:block; }
.dtable tr:hover td { background:rgba(255,255,255,.03); }
/* Pagination */
.pager { display:flex; gap:8px; align-items:center; justify-content:center; margin:16px 0; }
.pager button { min-width:32px; }
.pager span { color:var(--dim); font-size:11px; }
/* Modal / Overlay */
.overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.85); z-index:50; justify-content:center; align-items:center; padding:20px; }
.overlay.active { display:flex; }
.obox { background:var(--card); border:1px solid var(--line); border-radius:10px; max-width:90vw; max-height:90vh; overflow:auto; padding:16px; }
.obox img { max-width:100%; border-radius:6px; }
.obox .ocap { margin-top:8px; font-size:12px; white-space:pre-wrap; }
.close { position:absolute; top:12px; right:16px; font-size:20px; color:var(--fg); cursor:pointer; background:transparent; border:0; }
/* Utility */
.empty { color:var(--dim); padding:30px; text-align:center; grid-column:1/-1; }
.hide { display:none !important; }
.filter-group { display:flex; gap:4px; }
</style>
</head>
<body>
<header>
  <h1>🎬 Shishi Asset Dashboard</h1>
  <div class="sub">ローカル資産管理 — 動画・フレーム・メタデータ統合ビュー</div>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <div class="view-group" id="viewGroup">
      <button data-view="videos" class="active" title="動画ギャラリー">🎬 Videos</button>
      <button data-view="frames" title="フレームグリッド">🖼 Frames</button>
      <button data-view="dataset" title="データセットテーブル">📊 Dataset</button>
    </div>
    <div class="filter-group">
      <select id="videoFilter">
        <option value="">すべての動画</option>
      </select>
      <label style="color:var(--dim);font-size:11px;"><input type="checkbox" id="onlyWithCaptions" checked> キャプションあり</label>
    </div>
    <input type="search" id="q" placeholder="ID / タイトル / タグ で検索">
    <span class="sub" id="shown"></span>
  </div>
</header>
<main id="main"></main>

<div class="overlay" id="overlay">
  <button class="close" onclick="closeOverlay()">✕</button>
  <div class="obox">
    <img id="oimg" src="" alt="">
    <div class="ocap" id="ocap"></div>
  </div>
</div>

<script>
/* ---- EMBEDDED MANIFEST ---- */
const MANIFEST = __MANIFEST_JSON__;
/* --------------------------- */

let view = "videos";
let query = "";
let videoFilter = "";
let onlyWithCaptions = true;
let page = 1;
const PAGE_SIZE = 48;

function esc(s) { return (s||"").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#x27;"}[c])); }
function fmtBytes(b) { if (!b) return "-"; const u=["B","KB","MB","GB"]; let i=0; while(b>1024&&i<u.length-1){b/=1024;i++;} return b.toFixed(1)+" "+u[i]; }

/* Build flat frame list from manifest */
const allFrames = [];
const videoMap = {};
for (const v of MANIFEST.videos) {
  videoMap[v.video_id] = v;
  if (v.frames && v.frames.entries) {
    for (const e of v.frames.entries) {
      allFrames.push({ ...e, video_id: v.video_id, title: v.title || v.video_id });
    }
  }
}

/* Populate video filter dropdown */
const sel = document.getElementById("videoFilter");
for (const v of MANIFEST.videos) {
  const opt = document.createElement("option");
  opt.value = v.video_id;
  opt.textContent = (v.title || v.video_id) + " (" + (v.frames.count||0) + ")";
  sel.appendChild(opt);
}

/* Stats */
const s = MANIFEST.summary;
document.getElementById("stats").innerHTML = `
  <div class="stat">🎬 Videos <b>${s.total_videos_with_frames}</b></div>
  <div class="stat">✅ Approved <b>${s.total_videos_approved}</b></div>
  <div class="stat">💾 Downloaded <b>${s.total_videos_downloaded}</b></div>
  <div class="stat">🖼 Frames <b>${s.total_frames}</b></div>
  <div class="stat">📝 Captions <b>${s.caption_coverage}</b></div>
`;

/* ---- Video Gallery ---- */
function renderVideos() {
  const list = MANIFEST.videos.filter(v => {
    if (videoFilter && v.video_id !== videoFilter) return false;
    if (query && !(v.video_id + " " + (v.title||"")).toLowerCase().includes(query)) return false;
    return true;
  });

  const grid = document.createElement("div");
  grid.className = "gallery";
  if (!list.length) { grid.innerHTML = '<div class="empty">該当なし</div>'; }

  for (const v of list) {
    const card = document.createElement("article");
    card.className = "vcard";
    const thumb = v.frames.entries[0] ? `../${v.frames.entries[0].path}` : "";
    const statusClass = v.permission_status === "approved" ? "approved" : (v.permission_status === "pending" ? "pending" : "error");
    card.innerHTML = `
      <div class="vthumb"><img loading="lazy" src="${esc(thumb)}" alt="" onerror="this.style.opacity=0.3"></div>
      <div class="vinfo">
        <div class="vtitle">${esc(v.title || v.video_id)}</div>
        <div class="vmeta">
          <span class="badge ${statusClass}">${esc(v.permission_status)}</span>
          <span>🖼 ${v.frames.count||0} frames</span>
          <span>${fmtBytes(v.local_video.size_bytes)}</span>
        </div>
        <div class="vmeta" style="margin-top:2px;">
          <span>ID: ${esc(v.video_id)}</span>
          <a href="${esc(v.source_url||"#")}" target="_blank" rel="noreferrer" style="color:var(--info);">YouTube</a>
        </div>
        <div class="vactions">
          <button onclick="showVideoFrames('${esc(v.video_id)}')">🖼 フレーム表示</button>
          <button onclick="showVideoPath('${esc(v.video_id)}')">📂 動画パス</button>
        </div>
      </div>`;
    grid.appendChild(card);
  }
  return grid;
}

function showVideoFrames(vid) { videoFilter=vid; view="frames"; page=1; sel.value=vid; updateViewButtons(); render(); }
function showVideoPath(vid) { const v=videoMap[vid]; if(!v)return; alert("Local video:\n" + (v.local_video.path||"N/A")); }

/* ---- Frame Grid ---- */
function renderFrames() {
  let list = allFrames.filter(f => {
    if (videoFilter && f.video_id !== videoFilter) return false;
    if (onlyWithCaptions && !f.has_caption) return false;
    if (query && !(f.filename + " " + f.video_id + " " + (f.caption_text||"")).toLowerCase().includes(query)) return false;
    return true;
  });

  const total = list.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * PAGE_SIZE;
  const end = start + PAGE_SIZE;
  list = list.slice(start, end);

  const wrap = document.createElement("div");
  const grid = document.createElement("div");
  grid.className = "fgrid";

  if (!list.length) { grid.innerHTML = '<div class="empty">該当なし</div>'; }
  for (const f of list) {
    // Load caption text if available
    const capText = ""; // captions loaded on demand or embedded if small
    const card = document.createElement("div");
    card.className = "fcard";
    card.innerHTML = `
      <img loading="lazy" src="../${esc(f.path)}" alt="" onclick="openOverlay('../${esc(f.path)}','${esc(f.video_id)} ${esc(f.filename)}')" style="cursor:zoom-in;">
      <div class="fmeta">
        <div>${esc(f.video_id)} #${String(f.index).padStart(6,"0")}</div>
        ${f.has_caption ? `<div class="fcap">📝 ${esc(f.caption_path)}</div>` : ""}
      </div>`;
    grid.appendChild(card);
  }
  wrap.appendChild(grid);

  // Pager
  if (total > PAGE_SIZE) {
    const pager = document.createElement("div");
    pager.className = "pager";
    const prevBtn = document.createElement("button"); prevBtn.textContent = "←"; prevBtn.disabled = page<=1; prevBtn.onclick=()=>{page--;render();};
    const nextBtn = document.createElement("button"); nextBtn.textContent = "→"; nextBtn.disabled = page>=totalPages; nextBtn.onclick=()=>{page++;render();};
    const info = document.createElement("span"); info.textContent = `${page} / ${totalPages} (${total} frames)`;
    pager.appendChild(prevBtn); pager.appendChild(info); pager.appendChild(nextBtn);
    wrap.appendChild(pager);
  }

  document.getElementById("shown").textContent = `${total} frames`;
  return wrap;
}

/* ---- Dataset Table ---- */
function renderDataset() {
  let list = allFrames.filter(f => {
    if (videoFilter && f.video_id !== videoFilter) return false;
    if (onlyWithCaptions && !f.has_caption) return false;
    if (query && !(f.filename + " " + f.video_id).toLowerCase().includes(query)) return false;
    return true;
  });

  const total = list.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * PAGE_SIZE;
  const end = start + PAGE_SIZE;
  const pageList = list.slice(start, end);

  const wrap = document.createElement("div");
  const table = document.createElement("table");
  table.className = "dtable";
  table.innerHTML = `<thead><tr>
    <th>#</th><th>Image</th><th>Video</th><th>Frame</th><th>Caption</th><th>Path</th>
  </tr></thead><tbody></tbody>`;
  const tbody = table.querySelector("tbody");

  if (!pageList.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">該当なし</td></tr>';
  } else {
    for (const f of pageList) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${f.index}</td>
        <td><img src="../${esc(f.path)}" loading="lazy" onclick="openOverlay('../${esc(f.path)}','${esc(f.video_id)} ${esc(f.filename)}')"></td>
        <td>${esc(f.video_id)}</td>
        <td>${esc(f.filename)}</td>
        <td>${f.has_caption ? esc(f.caption_path) : "—"}</td>
        <td><code style="font-size:10px;">${esc(f.path)}</code></td>`;
      tbody.appendChild(tr);
    }
  }
  wrap.appendChild(table);

  if (total > PAGE_SIZE) {
    const pager = document.createElement("div");
    pager.className = "pager";
    const prev = document.createElement("button"); prev.textContent="←"; prev.disabled=page<=1; prev.onclick=()=>{page--;render();};
    const next = document.createElement("button"); next.textContent="→"; next.disabled=page>=totalPages; next.onclick=()=>{page++;render();};
    const info = document.createElement("span"); info.textContent=`${page} / ${totalPages} (${total} rows)`;
    pager.appendChild(prev); pager.appendChild(info); pager.appendChild(next);
    wrap.appendChild(pager);
  }

  document.getElementById("shown").textContent = `${total} rows`;
  return wrap;
}

/* ---- Overlay ---- */
function openOverlay(src, caption) {
  document.getElementById("oimg").src = src;
  document.getElementById("ocap").textContent = caption;
  document.getElementById("overlay").classList.add("active");
}
function closeOverlay() { document.getElementById("overlay").classList.remove("active"); }

/* ---- Render dispatcher ---- */
function render() {
  const main = document.getElementById("main");
  main.innerHTML = "";
  if (view === "videos") {
    main.appendChild(renderVideos());
    document.getElementById("shown").textContent = MANIFEST.videos.length + " videos";
  } else if (view === "frames") {
    main.appendChild(renderFrames());
  } else if (view === "dataset") {
    main.appendChild(renderDataset());
  }
}

function updateViewButtons() {
  document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === view));
}

/* ---- Event bindings ---- */
for (const b of document.querySelectorAll("[data-view]")) {
  b.addEventListener("click", () => {
    view = b.dataset.view; page = 1; updateViewButtons(); render();
  });
}

document.getElementById("q").addEventListener("input", e => {
  query = e.target.value.trim().toLowerCase(); page = 1; render();
});

document.getElementById("videoFilter").addEventListener("change", e => {
  videoFilter = e.target.value; page = 1; render();
});

document.getElementById("onlyWithCaptions").addEventListener("change", e => {
  onlyWithCaptions = e.target.checked; page = 1; render();
});

// Close overlay on backdrop click
if(document.getElementById("overlay")){
  document.getElementById("overlay").addEventListener("click", e => {
    if (e.target.id === "overlay") closeOverlay();
  });
}

render();
</script>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description="Build Shishi asset dashboard")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to frame_manifest.json")
    parser.add_argument("--output", type=Path, required=True, help="Output HTML path")
    args = parser.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Inline preview captions from .txt files if available
    for v in manifest.get("videos", []):
        for e in v.get("frames", {}).get("entries", []):
            if e.get("has_caption") and e.get("caption_path"):
                cap_file = args.manifest.parent.parent / e["caption_path"]
                try:
                    with open(cap_file, "r", encoding="utf-8") as cf:
                        e["caption_text"] = cf.read().strip()
                except Exception:
                    e["caption_text"] = ""

    manifest_json = json.dumps(manifest, ensure_ascii=False)

    html = HTML_TEMPLATE.replace("__MANIFEST_JSON__", manifest_json)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[dashboard] wrote {args.output} ({len(html):,} bytes)")
    print(f"[dashboard] videos={len(manifest['videos'])}, frames={manifest['summary']['total_frames']}")
    print(f"[open] file://{args.output.resolve()}")


if __name__ == "__main__":
    main()
