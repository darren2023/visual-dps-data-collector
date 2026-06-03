/** 货位网格标注（透视变换 + 拖拽网格线，格式对齐 visual-dps / box_human_det） */

const getAnnCanvas = () => document.getElementById("annotate-canvas");
const getAnnCtx = () => {
  const c = getAnnCanvas();
  return c ? c.getContext("2d") : null;
};

const MAP_W = 600;
const MAP_H = 600;

let bgImage = new Image();
let shelfPoints = [];
let M_fwd = null;
let M_inv = null;
let gridRows = 4;
let gridCols = 4;
let layerYs = [];
let layerColXs = [];
let dragTarget = null;
let dragStartFlat = null;
let dragStartState = null;
let finalBoxes = [];
let currentVideoStem = "";
let currentSourceVideo = "";
let frameWidth = 0;
let frameHeight = 0;
let loadedBoxesOnly = [];
let loadedAnnotationSize = null;
let currentShelfCode = "SHELF_1";

const { mapPointsToVideoFrame, isNormPolygonValid } = window.previewLayout || {};

function ann$(sel) {
  return document.querySelector(sel);
}

function setAnnotateStatus(html, isError = false) {
  const el = ann$("#annotate-status");
  if (!el) return;
  el.classList.remove("hidden", "error");
  if (isError) el.classList.add("error");
  el.innerHTML = html;
}

function hideAnnotateStatus() {
  ann$("#annotate-status")?.classList.add("hidden");
}

function resetAnnotationState() {
  shelfPoints = [];
  M_fwd = null;
  M_inv = null;
  layerYs = [];
  layerColXs = [];
  dragTarget = null;
  dragStartFlat = null;
  dragStartState = null;
  finalBoxes = [];
  loadedBoxesOnly = [];
  loadedAnnotationSize = null;
}

function getPerspectiveTransform(src, dst) {
  const A = [];
  const B = [];
  for (let i = 0; i < 4; i += 1) {
    A.push([src[i][0], src[i][1], 1, 0, 0, 0, -src[i][0] * dst[i][0], -src[i][1] * dst[i][0]]);
    A.push([0, 0, 0, src[i][0], src[i][1], 1, -src[i][0] * dst[i][1], -src[i][1] * dst[i][1]]);
    B.push(dst[i][0]);
    B.push(dst[i][1]);
  }
  const h = math.lusolve(A, B).map((x) => x[0]);
  h.push(1.0);
  return [
    [h[0], h[1], h[2]],
    [h[3], h[4], h[5]],
    [h[6], h[7], h[8]],
  ];
}

function perspectiveTransform(pt, M) {
  const z = M[2][0] * pt[0] + M[2][1] * pt[1] + M[2][2];
  const x = (M[0][0] * pt[0] + M[0][1] * pt[1] + M[0][2]) / z;
  const y = (M[1][0] * pt[0] + M[1][1] * pt[1] + M[1][2]) / z;
  return [x, y];
}

function initGrid() {
  layerYs = [];
  layerColXs = [];
  for (let i = 0; i <= gridRows; i += 1) layerYs.push(i * (MAP_H / gridRows));
  for (let i = 0; i < gridRows; i += 1) {
    const cols = [];
    for (let j = 0; j <= gridCols; j += 1) cols.push(j * (MAP_W / gridCols));
    layerColXs.push(cols);
  }
}

function getDist(p, a, b) {
  const l2 = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
  if (l2 === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / l2));
  return Math.hypot(p[0] - (a[0] + t * (b[0] - a[0])), p[1] - (a[1] + t * (b[1] - a[1])));
}

function flattenBoxesFromPayload(data) {
  if (Array.isArray(data?.boxes)) return data.boxes;
  if (Array.isArray(data?.shelves)) {
    const out = [];
    data.shelves.forEach((shelf) => {
      const code = String(shelf?.shelf_code || "").trim();
      (shelf?.boxes || []).forEach((b) => {
        out.push({ ...b, shelf_code: b.shelf_code || code });
      });
    });
    return out;
  }
  return [];
}

function showCanvasWithImage(dataUrl, w, h) {
  const canvas = getAnnCanvas();
  if (!canvas) return;
  bgImage = new Image();
  bgImage.onload = () => {
    canvas.width = w || bgImage.width;
    canvas.height = h || bgImage.height;
    frameWidth = canvas.width;
    frameHeight = canvas.height;
    canvas.classList.remove("hidden");
    renderAnnotator();
  };
  bgImage.src = dataUrl;
}

function setupCanvasFromBase64(imageB64, w, h) {
  showCanvasWithImage(`data:image/jpeg;base64,${imageB64}`, w, h);
}

async function extractFirstFrameFromVideoFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.onloadeddata = () => {
      video.currentTime = 0;
    };
    video.onseeked = () => {
      const w = video.videoWidth;
      const h = video.videoHeight;
      if (!w || !h) {
        URL.revokeObjectURL(url);
        reject(new Error("无法读取视频尺寸"));
        return;
      }
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const cx = c.getContext("2d");
      cx.drawImage(video, 0, 0, w, h);
      const dataUrl = c.toDataURL("image/jpeg", 0.88);
      URL.revokeObjectURL(url);
      resolve({ dataUrl, width: w, height: h });
    };
    video.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("视频加载失败"));
    };
    video.src = url;
  });
}

function parsePrimaryShelf(data) {
  if (Array.isArray(data?.shelves) && data.shelves.length) {
    const shelf = data.shelves.find((s) => s && s.shelf_code) || data.shelves[0];
    return shelf || null;
  }
  if (Array.isArray(data?.boxes) && data.boxes.length) {
    const code =
      String(data?.source_info?.shelf_code || data?.source_info?.video_stem || currentVideoStem || "SHELF_1").trim() ||
      "SHELF_1";
    return {
      shelf_code: code,
      shelf_name: "",
      shelf_corners: Array.isArray(data.shelf_corners) ? data.shelf_corners : [],
      grid_shape: Array.isArray(data.grid_shape) ? data.grid_shape : [],
      boxes: data.boxes,
    };
  }
  return null;
}

function mapShelfToCanvas(shelf, annSize) {
  const fw = Math.max(1, frameWidth || getAnnCanvas()?.width || 1);
  const fh = Math.max(1, frameHeight || getAnnCanvas()?.height || 1);
  const mapPts = (pts, norm) => {
    if (!mapPointsToVideoFrame) return pts;
    return mapPointsToVideoFrame(pts, norm, annSize, fw, fh);
  };

  let corners = Array.isArray(shelf.shelf_corners)
    ? shelf.shelf_corners.map((p) => [Number(p[0]), Number(p[1])])
    : [];
  if (corners.length === 4 && annSize) {
    corners = mapPts(corners, null);
  }

  const boxes = (Array.isArray(shelf.boxes) ? shelf.boxes : []).map((box) => {
    const norm = isNormPolygonValid?.(box.video_polygon_norm) ? box.video_polygon_norm : null;
    const poly = Array.isArray(box.video_polygon) ? box.video_polygon : [];
    if (!poly.length || !annSize) return box;
    return {
      ...box,
      video_polygon: mapPts(poly, norm),
    };
  });

  return { ...shelf, shelf_corners: corners, boxes };
}

function applyAnnotationPayload(data) {
  if (data?.annotation_size) {
    loadedAnnotationSize = {
      width: Number(data.annotation_size.width) || 0,
      height: Number(data.annotation_size.height) || 0,
    };
  } else {
    loadedAnnotationSize = null;
  }

  const shelf = parsePrimaryShelf(data);
  if (!shelf) return false;

  currentShelfCode = String(shelf.shelf_code || currentVideoStem || "SHELF_1").trim() || "SHELF_1";
  const mapped = mapShelfToCanvas(shelf, loadedAnnotationSize);

  if (Array.isArray(mapped.grid_shape) && mapped.grid_shape.length === 2) {
    const r = Number(mapped.grid_shape[0]);
    const c = Number(mapped.grid_shape[1]);
    if (r > 0 && c > 0) {
      gridRows = r;
      gridCols = c;
    }
  }
  ann$("#annotate-rows").value = String(gridRows);
  ann$("#annotate-cols").value = String(gridCols);

  const corners = Array.isArray(mapped.shelf_corners) ? mapped.shelf_corners : [];
  if (corners.length === 4) {
    shelfPoints = corners.map((p) => [Number(p[0]), Number(p[1])]);
    const dst = [
      [0, 0],
      [MAP_W, 0],
      [MAP_W, MAP_H],
      [0, MAP_H],
    ];
    M_fwd = getPerspectiveTransform(shelfPoints, dst);
    M_inv = getPerspectiveTransform(dst, shelfPoints);
    initGrid();
    finalBoxes = mapped.boxes || [];
    loadedBoxesOnly = [];
    setAnnotateStatus("已加载已有标注，可拖拽网格线微调后保存（保存将覆盖原文件）。");
    return true;
  }

  finalBoxes = mapped.boxes || [];
  loadedBoxesOnly = finalBoxes.slice();
  shelfPoints = [];
  M_fwd = null;
  M_inv = null;
  if (loadedBoxesOnly.length) {
    setAnnotateStatus(
      `已加载 ${loadedBoxesOnly.length} 个货框（无 shelf_corners）。可点击「重新网格标注」。`
    );
  }
  return false;
}

async function loadExistingAnnotation(videoStem) {
  if (!videoStem) return null;
  try {
    const res = await fetch(`/api/annotations/by-video/${encodeURIComponent(videoStem)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function resolveAnnotateSelection(optionEl) {
  const opt = optionEl || ann$("#annotate-record")?.selectedOptions?.[0];
  if (!opt) return { recordId: "", videoStem: "", sourceVideo: "", hasVideo: false };
  const raw = opt.value || "";
  const videoStem = opt.dataset.videoStem || "";
  const recordId = raw.startsWith("stem:") ? "" : raw;
  return {
    recordId,
    videoStem,
    sourceVideo: opt.dataset.sourceVideo || "",
    hasVideo: opt.dataset.hasVideo === "1",
  };
}

async function loadFromRecord(recordIdOrStem) {
  const sel = ann$("#annotate-record");
  const opt =
    sel?.selectedOptions?.[0] ||
    (recordIdOrStem
      ? Array.from(sel?.options || []).find(
          (o) => o.value === recordIdOrStem || o.dataset.recordId === recordIdOrStem
        )
      : null);
  const { recordId, videoStem, sourceVideo, hasVideo } = resolveAnnotateSelection(opt);
  if (!recordId && !videoStem) return;

  resetAnnotationState();
  currentVideoStem = videoStem || recordIdOrStem || "";
  currentSourceVideo = sourceVideo || "";
  ann$("#annotate-stem").value = currentVideoStem;

  let frameLoaded = false;
  if (recordId && hasVideo) {
    setAnnotateStatus("正在加载视频首帧…");
    try {
      const frameRes = await fetch(`/api/records/${encodeURIComponent(recordId)}/annotation/frame`);
      if (frameRes.ok) {
        const frame = await frameRes.json();
        await new Promise((resolve) => {
          setupCanvasFromBase64(frame.image, frame.width, frame.height);
          if (bgImage.complete) resolve();
          else bgImage.onload = resolve;
        });
        frameLoaded = true;
      }
    } catch {
      /* 首帧失败时继续尝试加载标注 */
    }
  }

  const existing = await loadExistingAnnotation(currentVideoStem);
  if (existing) {
    currentShelfCode =
      String(existing?.shelves?.[0]?.shelf_code || existing?.source_info?.shelf_code || currentVideoStem || "SHELF_1").trim() ||
      "SHELF_1";
    applyAnnotationPayload(existing);
  }

  if (frameLoaded) {
    if (existing) {
      setAnnotateStatus("已加载视频首帧与已有标注，可继续编辑。");
    } else {
      hideAnnotateStatus();
      setAnnotateStatus("请依次点击 4 个点标定货架外框（左上→右上→右下→左下）。");
    }
  } else if (existing) {
    setAnnotateStatus(
      "已加载已有标注；该记录无配套视频，请上传<strong>本地视频</strong>（与 source_video 同名）以显示首帧背景。"
    );
  } else if (recordId) {
    setAnnotateStatus("该记录无配套视频且无已存标注，请上传本地视频进行标注。", true);
  } else {
    setAnnotateStatus("请上传本地视频以显示首帧，或继续编辑已有标注网格数据。", true);
  }
}

async function loadFromLocalVideo(file) {
  resetAnnotationState();
  currentVideoStem = file.name.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_");
  currentSourceVideo = file.name;
  ann$("#annotate-stem").value = currentVideoStem;
  setAnnotateStatus("正在提取视频首帧…");
  const { dataUrl, width, height } = await extractFirstFrameFromVideoFile(file);
  await new Promise((resolve) => {
    showCanvasWithImage(dataUrl, width, height);
    if (bgImage.complete) resolve();
    else bgImage.onload = resolve;
  });
  currentShelfCode = currentVideoStem || "SHELF_1";

  const existing = await loadExistingAnnotation(currentVideoStem);
  if (existing) {
    currentShelfCode =
      String(existing?.shelves?.[0]?.shelf_code || existing?.source_info?.shelf_code || currentVideoStem || "SHELF_1").trim() ||
      "SHELF_1";
    applyAnnotationPayload(existing);
  } else {
    hideAnnotateStatus();
    setAnnotateStatus("请依次点击 4 个点标定货架外框（左上→右上→右下→左下）。");
  }
}

function buildFinalBoxesFromGrid() {
  let boxId = 1;
  finalBoxes = [];
  loadedBoxesOnly = [];
  const fw = Math.max(1, frameWidth || getAnnCanvas()?.width || 1);
  const fh = Math.max(1, frameHeight || getAnnCanvas()?.height || 1);
  for (let i = 0; i < gridRows; i += 1) {
    for (let j = 0; j < gridCols; j += 1) {
      const poly = [
        perspectiveTransform([layerColXs[i][j], layerYs[i]], M_inv),
        perspectiveTransform([layerColXs[i][j + 1], layerYs[i]], M_inv),
        perspectiveTransform([layerColXs[i][j + 1], layerYs[i + 1]], M_inv),
        perspectiveTransform([layerColXs[i][j], layerYs[i + 1]], M_inv),
      ];
      finalBoxes.push({
        box_id: boxId,
        layer: i + 1,
        column: j + 1,
        shelf_code: currentShelfCode,
        video_polygon: poly,
        video_polygon_norm: poly.map(([x, y]) => [x / fw, y / fh]),
      });
      boxId += 1;
    }
  }
}

function buildSavePayload() {
  buildFinalBoxesFromGrid();
  const stem = currentVideoStem;
  const shelfCode = currentShelfCode || stem || "SHELF_1";
  return {
    annotation_size: { width: frameWidth, height: frameHeight },
    source_info: {
      capture_source: "video",
      video_stem: stem,
      source_video: currentSourceVideo || `${stem}.mp4`,
      shelf_code: shelfCode,
    },
    shelves: [
      {
        shelf_code: shelfCode,
        shelf_name: "",
        shelf_corners: shelfPoints,
        grid_shape: [gridRows, gridCols],
        boxes: finalBoxes,
      },
    ],
  };
}

async function saveAnnotation() {
  const stem = (ann$("#annotate-stem")?.value || currentVideoStem || "").trim();
  if (!stem) {
    setAnnotateStatus("请填写视频主名（video_stem）", true);
    return;
  }
  if (shelfPoints.length < 4 || !M_inv) {
    setAnnotateStatus("请先完成 4 点货架标定并生成网格", true);
    return;
  }
  currentVideoStem = stem;
  const payload = buildSavePayload();
  setAnnotateStatus("正在保存…");
  const res = await fetch(`/api/annotations/by-video/${encodeURIComponent(stem)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  setAnnotateStatus(
    `✅ 已保存至 <code>localdata/json/annotations/${stem}.json</code>（${body.box_count ?? finalBoxes.length} 个货框，覆盖旧标注）`
  );
}

function renderAnnotator() {
  const ctx = getAnnCtx();
  if (!ctx || !bgImage.complete) return;
  ctx.drawImage(bgImage, 0, 0);

  if (loadedBoxesOnly.length && shelfPoints.length < 4) {
    ctx.strokeStyle = "rgba(0, 255, 128, 0.5)";
    ctx.lineWidth = 2;
    loadedBoxesOnly.forEach((box) => {
      const poly = box.video_polygon;
      if (!Array.isArray(poly) || poly.length < 3) return;
      ctx.beginPath();
      poly.forEach((pt, i) => {
        if (i === 0) ctx.moveTo(pt[0], pt[1]);
        else ctx.lineTo(pt[0], pt[1]);
      });
      ctx.closePath();
      ctx.stroke();
    });
  }

  if (shelfPoints.length > 0) {
    ctx.strokeStyle = "#2ecc71";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(shelfPoints[0][0], shelfPoints[0][1]);
    for (let i = 1; i < shelfPoints.length; i += 1) {
      ctx.lineTo(shelfPoints[i][0], shelfPoints[i][1]);
    }
    if (shelfPoints.length === 4) ctx.closePath();
    ctx.stroke();
    ctx.fillStyle = "#e74c3c";
    shelfPoints.forEach((p) => {
      ctx.beginPath();
      ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  if (M_inv) {
    ctx.strokeStyle = "#f1c40f";
    ctx.lineWidth = 2;
    for (let i = 1; i < gridRows; i += 1) {
      const p1 = perspectiveTransform([0, layerYs[i]], M_inv);
      const p2 = perspectiveTransform([MAP_W, layerYs[i]], M_inv);
      ctx.beginPath();
      ctx.moveTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]);
      ctx.stroke();
    }
    for (let i = 0; i < gridRows; i += 1) {
      for (let j = 1; j < gridCols; j += 1) {
        const p1 = perspectiveTransform([layerColXs[i][j], layerYs[i]], M_inv);
        const p2 = perspectiveTransform([layerColXs[i][j], layerYs[i + 1]], M_inv);
        ctx.beginPath();
        ctx.moveTo(p1[0], p1[1]);
        ctx.lineTo(p2[0], p2[1]);
        ctx.stroke();
      }
    }
  }
}

function bindCanvasEvents() {
  const canvas = getAnnCanvas();
  if (!canvas) return;

  canvas.onmousedown = (e) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;

    if (shelfPoints.length < 4) {
      shelfPoints.push([x, y]);
      if (shelfPoints.length === 4) {
        const dst = [
          [0, 0],
          [MAP_W, 0],
          [MAP_W, MAP_H],
          [0, MAP_H],
        ];
        M_fwd = getPerspectiveTransform(shelfPoints, dst);
        M_inv = getPerspectiveTransform(dst, shelfPoints);
        initGrid();
        loadedBoxesOnly = [];
        setAnnotateStatus("网格已生成，拖拽黄线对齐货框边界，完成后点击保存。");
      }
    } else if (M_inv) {
      for (let i = 1; i < gridRows; i += 1) {
        const p1 = perspectiveTransform([0, layerYs[i]], M_inv);
        const p2 = perspectiveTransform([MAP_W, layerYs[i]], M_inv);
        if (getDist([x, y], p1, p2) < 15) {
          dragTarget = { type: "h", i };
          dragStartFlat = perspectiveTransform([x, y], M_fwd);
          dragStartState = layerYs[i];
          return;
        }
      }
      for (let i = 0; i < gridRows; i += 1) {
        for (let j = 1; j < gridCols; j += 1) {
          const p1 = perspectiveTransform([layerColXs[i][j], layerYs[i]], M_inv);
          const p2 = perspectiveTransform([layerColXs[i][j], layerYs[i + 1]], M_inv);
          if (getDist([x, y], p1, p2) < 15) {
            dragTarget = { type: "v", i, j };
            dragStartFlat = perspectiveTransform([x, y], M_fwd);
            dragStartState = layerColXs[i][j];
            return;
          }
        }
      }
    }
    renderAnnotator();
  };

  canvas.onmousemove = (e) => {
    if (!dragTarget) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const flatPt = perspectiveTransform(
      [(e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY],
      M_fwd
    );
    if (dragTarget.type === "h") {
      const i = dragTarget.i;
      const dy = flatPt[1] - dragStartFlat[1];
      const newY = dragStartState + dy;
      layerYs[i] = Math.max(layerYs[i - 1] + 15, Math.min(layerYs[i + 1] - 15, newY));
    } else if (dragTarget.type === "v") {
      const { i, j } = dragTarget;
      const dx = flatPt[0] - dragStartFlat[0];
      const newX = dragStartState + dx;
      layerColXs[i][j] = Math.max(layerColXs[i][j - 1] + 10, Math.min(layerColXs[i][j + 1] - 10, newX));
    }
    renderAnnotator();
  };

  canvas.onmouseup = () => {
    dragTarget = null;
  };
}

function restartGridAnnotation() {
  shelfPoints = [];
  M_fwd = null;
  M_inv = null;
  layerYs = [];
  layerColXs = [];
  finalBoxes = [];
  loadedBoxesOnly = [];
  gridRows = Number(ann$("#annotate-rows")?.value) || 4;
  gridCols = Number(ann$("#annotate-cols")?.value) || 4;
  setAnnotateStatus("已重置，请重新点击 4 个点标定货架外框。");
  renderAnnotator();
}

function applyGridSizeFromInputs() {
  const r = Math.max(1, Math.min(20, Number(ann$("#annotate-rows")?.value) || 4));
  const c = Math.max(1, Math.min(20, Number(ann$("#annotate-cols")?.value) || 4));
  gridRows = r;
  gridCols = c;
  if (M_inv && shelfPoints.length === 4) {
    initGrid();
    renderAnnotator();
  }
}

/** 供 app.js 从历史记录跳转标注页 */
window.openAnnotateForRecord = async function openAnnotateForRecord(recordId, videoStem = "") {
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === "annotate");
  });
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  document.getElementById("panel-annotate")?.classList.add("active");
  if (typeof window.loadRecordsForAnnotate === "function") {
    await window.loadRecordsForAnnotate();
  }
  const sel = ann$("#annotate-record");
  if (sel) {
    const match = Array.from(sel.options).find(
      (o) =>
        o.value === recordId ||
        o.dataset.recordId === recordId ||
        (videoStem && o.dataset.videoStem === videoStem)
    );
    if (match) sel.value = match.value;
    if (videoStem) ann$("#annotate-stem").value = videoStem;
    await loadFromRecord(match?.value || recordId);
  }
};

let annotatePanelInited = false;

function initAnnotatePanel() {
  if (annotatePanelInited) return;
  annotatePanelInited = true;
  bindCanvasEvents();

  ann$("#annotate-load-record")?.addEventListener("click", async () => {
    const rid = ann$("#annotate-record")?.value;
    if (!rid) {
      setAnnotateStatus("请选择历史记录", true);
      return;
    }
    try {
      await loadFromRecord(rid);
    } catch (err) {
      setAnnotateStatus(`❌ ${err.message}`, true);
    }
  });

  ann$("#annotate-video")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await loadFromLocalVideo(file);
    } catch (err) {
      setAnnotateStatus(`❌ ${err.message}`, true);
    }
  });

  ann$("#annotate-json-upload")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const stem = (ann$("#annotate-stem")?.value || currentVideoStem || "").trim();
    if (!stem) {
      setAnnotateStatus("请先加载视频或填写 video_stem", true);
      e.target.value = "";
      return;
    }
    try {
      const fd = new FormData();
      fd.append("file", file);
      setAnnotateStatus("正在上传并覆盖保存…");
      const res = await fetch(`/api/annotations/by-video/${encodeURIComponent(stem)}/upload`, {
        method: "POST",
        body: fd,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || res.statusText);
      currentVideoStem = stem;
      const data = JSON.parse(await file.text());
      applyAnnotationPayload(data);
      setAnnotateStatus(
        `✅ 已上传覆盖（${body.box_count ?? "?"} 个货框）。可在网格上继续微调后再次保存。`
      );
    } catch (err) {
      setAnnotateStatus(`❌ ${err.message}`, true);
    }
    e.target.value = "";
  });

  ann$("#annotate-save")?.addEventListener("click", async () => {
    try {
      await saveAnnotation();
    } catch (err) {
      setAnnotateStatus(`❌ ${err.message}`, true);
    }
  });

  ann$("#annotate-restart")?.addEventListener("click", () => restartGridAnnotation());

  ann$("#annotate-rows")?.addEventListener("change", applyGridSizeFromInputs);
  ann$("#annotate-cols")?.addEventListener("change", applyGridSizeFromInputs);

  ann$("#annotate-download")?.addEventListener("click", async () => {
    const stem = (ann$("#annotate-stem")?.value || currentVideoStem || "").trim();
    if (!stem) {
      setAnnotateStatus("无 video_stem", true);
      return;
    }
    try {
      const res = await fetch(`/api/annotations/by-video/${encodeURIComponent(stem)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${stem}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      setAnnotateStatus(`❌ ${err.message}`, true);
    }
  });
}

function bootAnnotatePanel() {
  initAnnotatePanel();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootAnnotatePanel);
} else {
  bootAnnotatePanel();
}

