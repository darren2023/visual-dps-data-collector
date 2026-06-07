/** 货位标注（交互对齐现场 visual-dps：货架角点 + 货位四边形编辑） */

const getAnnCanvas = () => document.getElementById("annotate-canvas");
const getAnnCtx = () => {
  const c = getAnnCanvas();
  return c ? c.getContext("2d") : null;
};

let bgImage = new Image();
let gridRows = 4;
let gridCols = 4;
let finalBoxes = [];
let unbindVisualCanvas = null;
let currentVideoStem = "";
let currentSourceVideo = "";
let frameWidth = 0;
let frameHeight = 0;
let loadedAnnotationSize = null;
let currentShelfCode = "SHELF_1";
/** 缓存用户选择的本地视频，避免仅依赖 input.files 在部分浏览器下丢失 */
let cachedLocalVideoFile = null;
/** 从采集页跳转标注时携带的 record_id（非 UI 下拉） */
let pendingAnnotateRecordId = "";

const previewLayoutApi = window.previewLayout || {};
const mapPtsToVideoFrame = previewLayoutApi.mapPointsToVideoFrame;
const isNormPolyValid = previewLayoutApi.isNormPolygonValid;

function visualMode() {
  return window.AnnotateVisualMode;
}

function ann$(sel) {
  return document.querySelector(sel);
}

function setAnnotateStatus(html, isError = false) {
  const el = ann$("#annotate-status");
  if (!el) return;
  el.classList.remove("hidden", "error");
  if (isError) el.classList.add("error");
  else el.classList.remove("error");
  el.innerHTML = html;
  requestAnimationFrame(() => {
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function hideAnnotateStatus() {
  ann$("#annotate-status")?.classList.add("hidden");
}

function formatApiDetail(detail) {
  if (detail == null) return "";
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d?.msg ? d.msg : String(d)))
      .filter(Boolean)
      .join("; ");
  }
  return String(detail);
}

async function readApiErrorDetail(res) {
  try {
    const body = await res.json();
    return formatApiDetail(body.detail) || res.statusText;
  } catch {
    return res.statusText;
  }
}

/** 加载失败时：状态栏 + 弹窗，避免“无任何提示” */
function notifyAnnotateFailure(message, { alertUser = true } = {}) {
  const msg = String(message || "未知错误").trim() || "未知错误";
  console.error("[annotate]", msg);
  setAnnotateStatus(`❌ ${msg}`, true);
  if (alertUser) {
    window.alert(`标注页加载失败：\n\n${msg}`);
  }
}

function ensureAnnotatePanelVisible() {
  const panel = document.getElementById("panel-annotate");
  if (panel?.classList.contains("active")) return;
  const tab = document.querySelector('.tab[data-tab="annotate"]');
  if (tab) tab.click();
}

function countAnnotationBoxes(data) {
  if (!data) return 0;
  if (Array.isArray(data.boxes)) return data.boxes.length;
  let n = 0;
  (data.shelves || []).forEach((s) => {
    n += Array.isArray(s?.boxes) ? s.boxes.length : 0;
  });
  return n;
}

function updateAnnotateVerifyPanel(info) {
  const el = document.getElementById("annotate-verify");
  if (!el) return;
  const {
    ok,
    recordId,
    videoStem,
    sourceVideo,
    localVideoName,
    frameLoaded,
    frameSize,
    frameSource,
    annotationLoaded,
    boxCount,
    annSize,
    stemMatch,
    videoNameMatch,
    errors = [],
  } = info;
  el.classList.remove("hidden", "ok", "warn", "fail");
  if (ok) el.classList.add("ok");
  else if (frameLoaded || annotationLoaded) el.classList.add("warn");
  else el.classList.add("fail");

  const lines = [];
  if (ok) {
    lines.push("<strong>对照预览已就绪</strong>：首帧 + 标注网格已叠加，请目视货框是否与视频一致。");
  } else if (frameLoaded && !annotationLoaded) {
    lines.push("<strong>仅有首帧</strong>：未加载到标注 JSON，无法对照。");
  } else if (!frameLoaded && annotationLoaded) {
    lines.push("<strong>仅有标注数据</strong>：无首帧背景，无法目视对照。");
  } else {
    lines.push("<strong>加载未完成</strong>：无法对照，请根据下方明细排查。");
  }
  if (errors.length) {
    lines.push(`<p class="verify-err">${errors.map((e) => `• ${e}`).join("<br/>")}</p>`);
  }

  el.innerHTML = `
    ${lines.join("")}
    <dl>
      <dt>记录 ID</dt><dd>${recordId || "—"}</dd>
      <dt>video_stem</dt><dd>${videoStem || "—"} ${stemMatch === false ? '<span class="verify-warn">（与标注 JSON 内不一致）</span>' : ""}</dd>
      <dt>标注 JSON</dt><dd>${annotationLoaded ? `已加载，${boxCount} 个货框` : "未加载"}${annSize ? `；标注分辨率 ${annSize.w}×${annSize.h}` : ""}</dd>
      <dt>视频首帧</dt><dd>${frameLoaded ? `已显示 ${frameSize || ""}（${frameSource || "—"}）` : "未显示"}</dd>
      <dt>记录 source_video</dt><dd>${sourceVideo || "—"}</dd>
      <dt>本地视频文件</dt><dd>${localVideoName || "未选择"} ${videoNameMatch === false ? '<span class="verify-warn">（与 source_video 文件名不一致）</span>' : ""}</dd>
    </dl>
  `;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function resetAnnotationState() {
  visualMode()?.reset();
  finalBoxes = [];
  loadedAnnotationSize = null;
  syncAnnotateCellPanel(null);
}

function syncGridFromInputs() {
  const r = Math.max(1, Math.min(8, Number(ann$("#annotate-rows")?.value) || 4));
  const c = Math.max(1, Math.min(8, Number(ann$("#annotate-cols")?.value) || 4));
  gridRows = r;
  gridCols = c;
  visualMode()?.setGridSize(r, c);
}

function syncAnnotateCellPanel(panel) {
  const wrap = document.getElementById("annotate-cell-panel");
  const pos = document.getElementById("annotate-cell-pos");
  const input = document.getElementById("annotate-box-id");
  if (!wrap) return;
  if (!panel) {
    wrap.classList.add("hidden");
    if (input) input.value = "";
    return;
  }
  wrap.classList.remove("hidden");
  if (pos) pos.textContent = `第 ${panel.row} 层 · 第 ${panel.col} 列`;
  if (input) {
    input.value = panel.value || "";
    input.placeholder = panel.defaultId || "";
  }
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

/** 将首帧绘制到标注画布（单一 onload，避免被覆盖导致画布不显示） */
function showCanvasWithImage(dataUrl, w, h) {
  return new Promise((resolve, reject) => {
    const canvas = getAnnCanvas();
    if (!canvas) {
      reject(new Error("标注画布未找到，请刷新页面"));
      return;
    }
    bgImage = new Image();
    bgImage.onload = () => {
      canvas.width = w || bgImage.naturalWidth || bgImage.width;
      canvas.height = h || bgImage.naturalHeight || bgImage.height;
      frameWidth = canvas.width;
      frameHeight = canvas.height;
      canvas.classList.remove("hidden");
      visualMode()?.ensureDefaultShelf(frameWidth, frameHeight);
      renderAnnotator();
      resolve({ width: frameWidth, height: frameHeight });
    };
    bgImage.onerror = () => reject(new Error("首帧图片加载失败"));
    bgImage.src = dataUrl;
  });
}

function setupCanvasFromBase64(imageB64, w, h) {
  return showCanvasWithImage(`data:image/jpeg;base64,${imageB64}`, w, h);
}

async function loadFirstFrameOntoCanvas(dataUrl, width, height) {
  ensureAnnotatePanelVisible();
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  await showCanvasWithImage(dataUrl, width, height);
}

function getAnnotateLocalVideoFile() {
  return cachedLocalVideoFile || ann$("#annotate-video")?.files?.[0] || null;
}

function rememberLocalVideoFile(file) {
  cachedLocalVideoFile = file || null;
}

async function fetchRecordMeta(recordId) {
  try {
    const res = await fetch(`/api/records/${encodeURIComponent(recordId)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function loadAnnotationForRecord(recordId, videoStem) {
  if (recordId) {
    try {
      const res = await fetch(`/api/records/${encodeURIComponent(recordId)}/annotation.json`);
      if (res.ok) return await res.json();
    } catch {
      /* 回退按 video_stem */
    }
  }
  return loadExistingAnnotation(videoStem);
}

function localVideoMatchesRecord(file, sourceVideo, videoStem) {
  if (!file) return false;
  const name = file.name;
  if (sourceVideo && name === sourceVideo) return true;
  const localStem = name.replace(/\.[^.]+$/, "");
  if (videoStem && localStem === videoStem) return true;
  const norm = (s) => String(s || "").replace(/[^\w.-]+/g, "_").toLowerCase();
  return videoStem && norm(localStem) === norm(videoStem);
}

async function tryLoadRecordFrameFromApi(recordId) {
  const frameRes = await fetch(`/api/records/${encodeURIComponent(recordId)}/annotation/frame`);
  if (!frameRes.ok) return { ok: false, detail: await readApiErrorDetail(frameRes) };
  const frame = await frameRes.json();
  await loadFirstFrameOntoCanvas(
    `data:image/jpeg;base64,${frame.image}`,
    frame.width,
    frame.height
  );
  return { ok: true };
}

async function tryLoadFrameByVideoStem(videoStem) {
  const stem = String(videoStem || "").trim();
  if (!stem) return { ok: false, detail: "无 video_stem" };
  const frameRes = await fetch(`/api/annotations/by-video/${encodeURIComponent(stem)}/frame`);
  if (!frameRes.ok) return { ok: false, detail: await readApiErrorDetail(frameRes) };
  const frame = await frameRes.json();
  await loadFirstFrameOntoCanvas(
    `data:image/jpeg;base64,${frame.image}`,
    frame.width,
    frame.height
  );
  return { ok: true };
}

async function tryLoadRecordFrameFromLocalFile(file) {
  let clientErr = null;
  try {
    const { dataUrl, width, height } = await extractFirstFrameFromVideoFile(file);
    await loadFirstFrameOntoCanvas(dataUrl, width, height);
    return { ok: true, via: "browser" };
  } catch (err) {
    clientErr = err;
  }
  setAnnotateStatus("浏览器无法解码，正在由服务端提取首帧…");
  const fd = new FormData();
  fd.append("file", file, file.name || "video.mp4");
  const res = await fetch("/api/annotate/extract-frame", { method: "POST", body: fd });
  if (!res.ok) {
    const detail = await readApiErrorDetail(res);
    throw new Error(detail || clientErr?.message || "服务端首帧提取失败");
  }
  const frame = await res.json();
  await loadFirstFrameOntoCanvas(
    `data:image/jpeg;base64,${frame.image}`,
    frame.width,
    frame.height
  );
  return { ok: true, via: "server" };
}

async function extractFirstFrameFromVideoFile(file) {
  const url = URL.createObjectURL(file);
  try {
    return await extractFirstFrameFromObjectUrl(url);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function extractFirstFrameFromObjectUrl(url) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.setAttribute("playsinline", "");
    video.setAttribute("webkit-playsinline", "");
    video.preload = "auto";
    video.style.cssText = "position:fixed;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none";
    document.body.appendChild(video);

    let settled = false;
    const finish = (err, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      video.pause();
      video.removeAttribute("src");
      video.load();
      video.remove();
      if (err) reject(err);
      else resolve(result);
    };
    const timer = setTimeout(() => finish(new Error("视频首帧提取超时（30s）")), 30000);

    const capture = () => {
      const w = video.videoWidth;
      const h = video.videoHeight;
      if (!w || !h) {
        finish(new Error("无法读取视频尺寸"));
        return;
      }
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const cx = c.getContext("2d");
      try {
        cx.drawImage(video, 0, 0, w, h);
        finish(null, { dataUrl: c.toDataURL("image/jpeg", 0.88), width: w, height: h });
      } catch (e) {
        finish(new Error(e?.message || "首帧绘制失败"));
      }
    };

    video.onerror = () => finish(new Error("视频加载失败"));
    video.oncanplay = () => {
      const runCapture = () => {
        video.pause();
        requestAnimationFrame(() => capture());
      };
      if (video.currentTime > 0.01) {
        video.onseeked = () => runCapture();
        video.currentTime = 0;
      } else {
        runCapture();
      }
    };
    video.src = url;
    video.load();
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
  const vm = visualMode();
  if (!vm) return false;

  vm.loadShelf(shelf, {
    mapPointsToFrame: mapPtsToVideoFrame,
    isNormValid: isNormPolyValid,
    annotationSize: loadedAnnotationSize,
    frameWidth,
    frameHeight,
  });
  const gs = vm.getGridSize();
  gridRows = gs.rows;
  gridCols = gs.cols;
  ann$("#annotate-rows").value = String(gridRows);
  ann$("#annotate-cols").value = String(gridCols);
  syncAnnotateCellPanel(null);
  renderAnnotator();
  return vm.isGridReady();
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

async function loadAnnotateFirstFrame() {
  ensureAnnotatePanelVisible();
  const stem = (ann$("#annotate-stem")?.value || currentVideoStem || "").trim();
  if (!stem) {
    setAnnotateStatus("请填写 video_stem（视频主名）", true);
    return;
  }
  const localFile = getAnnotateLocalVideoFile();
  if (!localFile) {
    setAnnotateStatus("请先选择本地视频文件", true);
    return;
  }

  const recordId = pendingAnnotateRecordId || "";
  resetAnnotationState();
  pendingAnnotateRecordId = recordId;
  const verifyErrors = [];

  let sourceVideo = "";
  if (recordId) {
    const meta = await fetchRecordMeta(recordId);
    if (meta) {
      sourceVideo = String(meta.source_video || "").trim();
    }
  }

  currentVideoStem = stem;
  currentSourceVideo = sourceVideo || "";
  ann$("#annotate-stem").value = currentVideoStem;

  let frameLoaded = false;
  let frameSource = "";
  let frameLoadError = "";
  const stemForFrame = currentVideoStem;

  setAnnotateStatus("正在加载视频首帧…");

  if (!localFile) {
    verifyErrors.push("未选择本地视频");
  } else {
    try {
      const local = await tryLoadRecordFrameFromLocalFile(localFile);
      if (local && local.ok) {
        frameLoaded = true;
        frameSource = local.via === "server" ? "local-server" : "local";
        if (!currentSourceVideo) currentSourceVideo = localFile.name;
      } else {
        frameLoadError = "本地首帧提取未返回有效结果";
        verifyErrors.push(frameLoadError);
      }
    } catch (err) {
      frameLoadError = err.message || String(err);
      verifyErrors.push(`首帧：${frameLoadError}`);
    }
  }

  if (!frameLoaded) {
    try {
      if (recordId) {
        const api = await tryLoadRecordFrameFromApi(recordId);
        if (api.ok) {
          frameLoaded = true;
          frameSource = "server";
        } else {
          frameLoadError = api.detail || frameLoadError;
        }
      }
      if (!frameLoaded && stemForFrame) {
        const stemApi = await tryLoadFrameByVideoStem(stemForFrame);
        if (stemApi.ok) {
          frameLoaded = true;
          frameSource = "server";
        } else if (!frameLoadError) {
          frameLoadError = stemApi.detail || "";
        }
      }
    } catch (err) {
      frameLoadError = err.message || String(err);
    }
  }

  if (!frameLoaded && !localFile) {
    frameLoadError = frameLoadError || "请先在「本地视频」选择 mp4 文件";
  }

  let existing = null;
  let annotationLoaded = false;
  let boxCount = 0;
  let annStem = "";
  try {
    existing = await loadAnnotationForRecord(recordId, currentVideoStem);
    if (existing) {
      annotationLoaded = true;
      boxCount = countAnnotationBoxes(existing);
      annStem = String(existing?.source_info?.video_stem || "").trim();
      currentShelfCode =
        String(existing?.shelves?.[0]?.shelf_code || existing?.source_info?.shelf_code || currentVideoStem || "SHELF_1").trim() ||
        "SHELF_1";
      applyAnnotationPayload(existing);
    } else if (recordId || stemForFrame) {
      verifyErrors.push(
        `未找到标注 JSON（video_stem=${currentVideoStem || stemForFrame}，记录=${recordId || "—"}）`
      );
    }
  } catch (err) {
    verifyErrors.push(`标注叠加失败：${err.message || err}`);
    console.error("[annotate] applyAnnotationPayload", err);
  }

  const videoNameMatch =
    !localFile || !sourceVideo ? null : localVideoMatchesRecord(localFile, sourceVideo, currentVideoStem);
  const stemMatch = !annStem || !currentVideoStem ? null : annStem === currentVideoStem;
  const annSize =
    loadedAnnotationSize?.width > 0
      ? { w: loadedAnnotationSize.width, h: loadedAnnotationSize.height }
      : null;
  const frameSize = frameWidth && frameHeight ? `${frameWidth}×${frameHeight}` : "";
  const previewReady = frameLoaded && annotationLoaded && visualMode()?.isGridReady();

  if (previewReady) {
    setAnnotateStatus(
      `✅ 对照预览就绪：记录「${currentVideoStem}」共 ${boxCount} 个货框已叠加在首帧上，请目视网格是否与视频一致。`
    );
  } else if (frameLoaded && annotationLoaded) {
    setAnnotateStatus(
      `⚠️ 首帧已显示，标注已读入。请点击「生成货位」以 visual-dps 方式显示可编辑货位（${boxCount} 个货框数据）。`,
      true
    );
  } else if (frameLoaded) {
    setAnnotateStatus(
      `⚠️ 仅加载首帧，未加载标注 JSON，无法对照记录「${currentVideoStem || recordId || "?"}」的网格。`,
      true
    );
  } else if (annotationLoaded) {
    setAnnotateStatus(
      `⚠️ 已读取标注（${boxCount} 个货框），但首帧未显示：${frameLoadError || "请选择本地视频后重试"}`,
      true
    );
  } else {
    const summary = frameLoadError || verifyErrors[0] || "首帧与标注均未加载";
    notifyAnnotateFailure(summary, { alertUser: true });
  }

  if (sourceVideo && localFile && videoNameMatch === false) {
    verifyErrors.push(`本地视频「${localFile.name}」与记录 source_video「${sourceVideo}」不一致，请确认是否为同一文件`);
  }
  if (stemMatch === false) {
    verifyErrors.push(`标注 JSON 内 video_stem=${annStem}，与当前记录 ${currentVideoStem} 不一致`);
  }
  if (annSize && frameWidth && (annSize.w !== frameWidth || annSize.h !== frameHeight)) {
    verifyErrors.push(`标注分辨率 ${annSize.w}×${annSize.h} 与首帧 ${frameWidth}×${frameHeight} 不同，已按比例映射坐标`);
  }

  updateAnnotateVerifyPanel({
    ok: previewReady,
    recordId,
    videoStem: currentVideoStem,
    sourceVideo,
    localVideoName: localFile?.name || "",
    frameLoaded,
    frameSize,
    frameSource,
    annotationLoaded,
    boxCount,
    annSize,
    stemMatch,
    videoNameMatch,
    errors: verifyErrors,
  });

  if (frameLoaded || annotationLoaded) {
    renderAnnotator();
  }

  if (!frameLoaded && !annotationLoaded) {
    return;
  }
  if (!previewReady && (frameLoaded || annotationLoaded)) {
    window.alert(
      `对照预览未完全就绪：\n\n${verifyErrors.length ? verifyErrors.join("\n") : "首帧或货架四角未齐备"}\n\n详见页面上「对照明细」区域。`
    );
  }
  pendingAnnotateRecordId = "";
}

async function loadFromLocalVideo(file) {
  rememberLocalVideoFile(file);
  resetAnnotationState();
  currentVideoStem = file.name.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_");
  currentSourceVideo = file.name;
  ann$("#annotate-stem").value = currentVideoStem;
  setAnnotateStatus("正在提取视频首帧…");
  const { dataUrl, width, height } = await extractFirstFrameFromVideoFile(file);
  await loadFirstFrameOntoCanvas(dataUrl, width, height);
  currentShelfCode = currentVideoStem || "SHELF_1";

  const existing = await loadExistingAnnotation(currentVideoStem);
  if (existing) {
    currentShelfCode =
      String(existing?.shelves?.[0]?.shelf_code || existing?.source_info?.shelf_code || currentVideoStem || "SHELF_1").trim() ||
      "SHELF_1";
    applyAnnotationPayload(existing);
  } else {
    setAnnotateStatus(
      "首帧已加载：拖动绿色货架角点，设置行列后点「生成货位」，再对照货位形状。"
    );
  }
}

function buildSavePayload() {
  syncGridFromInputs();
  const vm = visualMode();
  finalBoxes = vm ? vm.buildBoxes(frameWidth, frameHeight) : [];
  const gs = vm?.getGridSize() || { rows: gridRows, cols: gridCols };
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
        shelf_corners: vm ? vm.getShelfCorners() : [],
        grid_shape: [gs.rows, gs.cols],
        boxes: finalBoxes,
      },
    ],
  };
}

function annotateSaveQueryParams() {
  const qs = new URLSearchParams();
  if (ann$("#annotate-preserve-existing")?.checked) qs.set("preserve_existing", "true");
  if (ann$("#annotate-recompute-collisions")?.checked) qs.set("recompute_collisions", "true");
  if (pendingAnnotateRecordId) qs.set("record_ids", pendingAnnotateRecordId);
  const s = qs.toString();
  return s ? `?${s}` : "";
}

function encodeRecordIdForApi(recordId) {
  return String(recordId || "")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function formatRecomputeStatus(recompute) {
  if (!recompute) return "";
  if (recompute.status === "skipped") {
    return ` · 碰撞重算跳过：${recompute.reason || "无关联记录"}`;
  }
  const ok = (recompute.recomputed || []).length;
  const bad = (recompute.errors || []).length;
  if (!ok && bad) {
    return ` · 碰撞重算失败：${recompute.errors.map((e) => e.error).join("; ")}`;
  }
  return ` · 已重算碰撞 ${ok} 条记录（复用骨架）${bad ? `，失败 ${bad} 条` : ""}`;
}

async function saveAnnotation() {
  const stem = (ann$("#annotate-stem")?.value || currentVideoStem || "").trim();
  if (!stem) {
    setAnnotateStatus("请填写视频主名（video_stem）", true);
    return;
  }
  const vm = visualMode();
  if (!vm?.shelfCornersReady()) {
    setAnnotateStatus("请先标定货架四角（拖动红色角点）", true);
    return;
  }
  if (!vm.isGridReady()) {
    setAnnotateStatus("请先点击「生成货位」", true);
    return;
  }
  currentVideoStem = stem;
  const payload = buildSavePayload();
  const recompute = !!ann$("#annotate-recompute-collisions")?.checked;
  setAnnotateStatus(recompute ? "正在保存并重算碰撞…" : "正在保存…");
  const res = await fetch(
    `/api/annotations/by-video/${encodeURIComponent(stem)}${annotateSaveQueryParams()}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(formatApiDetail(body.detail) || body.detail || res.statusText);
  const savedStem = body.video_stem || stem;
  currentVideoStem = savedStem;
  if (savedStem !== stem) ann$("#annotate-stem").value = savedStem;
  setAnnotateStatus(
    `✅ ${body.message || "已保存"}：<code>annotations/${savedStem}.json</code>（${body.box_count ?? finalBoxes.length} 个货框）${formatRecomputeStatus(body.recompute)}`
  );
}

async function recomputeCollisionsOnly() {
  const stem = (ann$("#annotate-stem")?.value || currentVideoStem || "").trim();
  if (!pendingAnnotateRecordId) {
    setAnnotateStatus("请从回放/采集记录进入标注页，或保存时勾选重算碰撞", true);
    return;
  }
  setAnnotateStatus("正在重算碰撞（复用已有骨架）…");
  const payload = stem ? { annotation_stem: stem } : {};
  const res = await fetch(
    `/api/records/${encodeRecordIdForApi(pendingAnnotateRecordId)}/recompute-collisions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(formatApiDetail(body.detail) || body.detail || res.statusText);
  const row = (body.recomputed || [])[0];
  const frames = row?.frame_count ?? "?";
  const ann = row?.annotation_file || stem;
  setAnnotateStatus(
    `✅ 碰撞已重算（${ann}）：记录 ${pendingAnnotateRecordId}，${frames} 帧骨架未重新推理。`
  );
}

function renderAnnotator() {
  const ctx = getAnnCtx();
  if (!ctx || !bgImage.complete) return;
  visualMode()?.render(ctx, bgImage);
}

function bindCanvasEvents() {
  if (unbindVisualCanvas) return;
  const canvas = getAnnCanvas();
  const vm = visualMode();
  if (!canvas || !vm) return;
  unbindVisualCanvas = vm.bindCanvas(canvas, {
    onSelectionChange: (panel) => {
      syncAnnotateCellPanel(panel);
      renderAnnotator();
    },
    onRender: () => renderAnnotator(),
  });
}

function restartGridAnnotation() {
  syncGridFromInputs();
  visualMode()?.reset();
  visualMode()?.ensureDefaultShelf(frameWidth, frameHeight);
  syncAnnotateCellPanel(null);
  setAnnotateStatus("已重置货架：拖动绿色角点 →「生成货位」→ 编辑货位。");
  renderAnnotator();
}

function applyGridSizeFromInputs() {
  syncGridFromInputs();
}

function confirmGenerateGrid() {
  syncGridFromInputs();
  const vm = visualMode();
  if (!vm) return;
  const result = vm.confirmGenerateGrid();
  if (!result.ok) {
    setAnnotateStatus(result.message, true);
    return;
  }
  setAnnotateStatus(result.message);
  renderAnnotator();
}

/** 供 app.js 从采集页跳转标注（非回放） */
window.openAnnotateForRecord = async function openAnnotateForRecord(recordId, videoStem = "") {
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === "annotate");
  });
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  document.getElementById("panel-annotate")?.classList.add("active");
  if (typeof window.initAnnotatePanel === "function") window.initAnnotatePanel();

  pendingAnnotateRecordId = String(recordId || "").trim();
  let stem = String(videoStem || "").trim();
  if (pendingAnnotateRecordId) {
    const meta = await fetchRecordMeta(pendingAnnotateRecordId);
    if (meta) {
      stem = String(meta.video_stem || meta.display_name || stem || pendingAnnotateRecordId).trim();
    }
  }
  if (stem) ann$("#annotate-stem").value = stem;
  currentVideoStem = stem;
  setAnnotateStatus(
    `已关联记录「${stem || pendingAnnotateRecordId}」：请选择<strong>本地视频</strong>（与采集视频一致），再点「加载首帧」。`
  );
};

let annotatePanelInited = false;

function initAnnotatePanel() {
  if (annotatePanelInited) return;
  annotatePanelInited = true;
  bindCanvasEvents();

  ann$("#annotate-load-frame")?.addEventListener("click", async () => {
    try {
      await loadAnnotateFirstFrame();
    } catch (err) {
      notifyAnnotateFailure(err.message || String(err));
    }
  });

  ann$("#annotate-video")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) {
      rememberLocalVideoFile(null);
      return;
    }
    rememberLocalVideoFile(file);
    const stem = (ann$("#annotate-stem")?.value || "").trim();
    if (!stem) {
      const guess = file.name.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_");
      ann$("#annotate-stem").value = guess;
    }
    setAnnotateStatus(`已选择「${file.name}」，请点击「加载首帧」。`);
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
      setAnnotateStatus("正在上传保存…");
      const res = await fetch(
        `/api/annotations/by-video/${encodeURIComponent(stem)}/upload${annotateSaveQueryParams()}`,
        { method: "POST", body: fd }
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiDetail(body.detail) || body.detail || res.statusText);
      const savedStem = body.video_stem || stem;
      currentVideoStem = savedStem;
      if (savedStem !== stem) ann$("#annotate-stem").value = savedStem;
      const data = JSON.parse(await file.text());
      applyAnnotationPayload(data);
      setAnnotateStatus(
        `✅ ${body.message || "已上传"}（${body.box_count ?? "?"} 个货框）${formatRecomputeStatus(body.recompute)}`
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

  ann$("#annotate-recompute-only")?.addEventListener("click", async () => {
    try {
      await recomputeCollisionsOnly();
    } catch (err) {
      setAnnotateStatus(`❌ ${err.message}`, true);
    }
  });

  ann$("#annotate-restart")?.addEventListener("click", () => restartGridAnnotation());

  ann$("#annotate-confirm-grid")?.addEventListener("click", () => confirmGenerateGrid());

  ann$("#annotate-delete-cell")?.addEventListener("click", () => {
    const panel = visualMode()?.getSelectedCellPanel();
    if (!panel) {
      setAnnotateStatus("请先在画面上点击选中一个货位", true);
      return;
    }
    if (
      !window.confirm(`确定删除第 ${panel.row} 层 · 第 ${panel.col} 列货位？删除后可重新「生成货位」恢复。`)
    ) {
      return;
    }
    visualMode()?.deleteSelectedCell();
    syncAnnotateCellPanel(null);
    renderAnnotator();
    setAnnotateStatus("已删除货位。");
  });

  ann$("#annotate-box-id")?.addEventListener("input", (e) => {
    const panel = visualMode()?.getSelectedCellPanel();
    if (!panel) return;
    visualMode()?.setBoxId(panel.rowIdx, panel.colIdx, e.target.value);
    renderAnnotator();
  });

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

window.initAnnotatePanel = initAnnotatePanel;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootAnnotatePanel);
} else {
  bootAnnotatePanel();
}

