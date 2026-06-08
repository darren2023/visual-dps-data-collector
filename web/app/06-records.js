/** 回放记录列表与打开记录 */
const RECORDS_VISIBLE_PER_GROUP = 8;
/** 机位分组展开条数上限（groupKey -> limit） */
const recordGroupVisibleLimits = new Map();
let playbackRecordsCache = [];

function recordItemEsc(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;");
}

function recordSearchBlob(s) {
  const name = s.display_name || s.record_id || "";
  const review = s.event_review_label || reviewStatusLabel(s.event_review_status);
  return `${name} ${s.record_id || ""} ${s.video_stem || ""} ${s.camera_label || ""} ${s.camera_slug || ""} ${review}`.toLowerCase();
}

function reviewStatusLabel(status) {
  if (status === "completed") return "已复核";
  if (status === "no_collision") return "无碰撞";
  if (status === "in_progress") return "复核中";
  return "未复核";
}

function reviewStatusClass(status) {
  if (status === "completed" || status === "no_collision") return "review-completed";
  if (status === "in_progress") return "review-in-progress";
  return "review-not-started";
}

function isReviewTerminalStatus(status) {
  return status === "completed" || status === "no_collision";
}

function renderReviewPill(status, label = "") {
  const st = status || "not_started";
  const text = label || reviewStatusLabel(st);
  return `<span class="record-review-pill ${reviewStatusClass(st)}" title="人工事件复核状态">${text}</span>`;
}

/** 本地即时更新单条/机位分组的复核状态，避免等慢接口返回 */
function patchPlaybackRecordReviewStatus(recordId, status, label = "") {
  if (!recordId) return;
  const st = status || "not_started";
  const labelText = label || reviewStatusLabel(st);
  let changed = false;
  playbackRecordsCache = playbackRecordsCache.map((item) => {
    if (item.record_id !== recordId) return item;
    changed = true;
    return {
      ...item,
      event_review_status: st,
      event_review_label: labelText,
    };
  });
  if (changed) renderPlaybackRecordsList(playbackRecordsCache);
}

function applyEventReviewPatchFromBody(body) {
  if (!currentRecordId || !body) return;
  const st =
    body.event_review_status ||
    body.event_review?.status ||
    (body.event_review?.verified_true?.length || body.event_review?.updated_at ? "in_progress" : null);
  if (!st) return;
  patchPlaybackRecordReviewStatus(
    currentRecordId,
    st,
    body.event_review_label || reviewStatusLabel(st)
  );
}

function aggregateReviewStatus(items) {
  const statuses = (items || []).map((s) => s.event_review_status || "not_started");
  if (!statuses.length) return "not_started";
  if (statuses.every((st) => isReviewTerminalStatus(st))) return "completed";
  if (statuses.every((st) => st === "not_started")) return "not_started";
  return "in_progress";
}

function renderRecordItem(s) {
  const name = s.display_name || s.record_id;
  const jsonFile = s.pose_label || s.pose_file || `${s.record_id}/manifest.json`;
  const esc = recordItemEsc;
  const reviewSt = s.event_review_status || "not_started";
  const reviewPill = renderReviewPill(reviewSt, s.event_review_label);
  const badges = [];
  if (s.frame_count != null) badges.push(`${s.frame_count} 帧`);
  if (s.has_video) badges.push("视频");
  if (s.has_stored_annotation || s.collision_enabled) badges.push("标注");
  if (s.collision_enabled) badges.push("碰撞");
  const badgeHtml = badges.map((b) => `<span class="record-badge">${b}</span>`).join("");
  return `
      <li class="record-item record-item-compact" data-record-id="${esc(s.record_id)}" data-display-name="${esc(name)}" data-pose-file="${esc(jsonFile)}" data-has-video="${s.has_video ? "1" : "0"}" data-search="${esc(recordSearchBlob(s))}">
        <div class="record-main record-main-compact">
          ${reviewPill}
          <strong class="record-name" title="${esc(name)}">${name}</strong>
          <span class="record-meta-inline">${badgeHtml}</span>
        </div>
        <span class="record-actions record-actions-compact">
          <a href="${recordApiUrl(s.record_id, "/manifest.json")}" download title="${esc(jsonFile)}">JSON</a>
          <a href="${recordApiUrl(s.record_id, "/export.xlsx")}" download title="导出 Excel">XLSX</a>
          ${s.has_video ? `<button type="button" data-annotate="${esc(s.record_id)}" data-stem="${esc(s.video_stem || name)}">标注</button>` : ""}
          <button type="button" class="danger-btn" data-delete="${esc(s.record_id)}" data-name="${esc(name)}">删</button>
        </span>
      </li>`;
}

function bindRecordListEvents(list) {
  list.querySelectorAll(".record-show-more").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const key = btn.dataset.groupKey;
      const total = parseInt(btn.dataset.groupTotal || "0", 10);
      if (key && total > 0) recordGroupVisibleLimits.set(key, total);
      renderPlaybackRecordsList(playbackRecordsCache);
    });
  });
  list.querySelectorAll(".record-item").forEach((li) => {
    li.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
      selectPlaybackRecordItem(li);
    });
    li.addEventListener("dblclick", (e) => {
      if (e.target.closest("a, button")) return;
      selectPlaybackRecordItem(li);
      startPlaybackFromSelectedRecord().catch((err) => setPlaybackInfo(`❌ ${err.message}`));
    });
  });
  const keepId = selectedPlaybackRecord?.recordId || currentRecordId || "";
  if (keepId) highlightPlaybackRecordInList(keepId);
  else updatePlaybackLoadButton();
  list.querySelectorAll("[data-annotate]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (typeof window.openAnnotateForRecord === "function") {
        window.openAnnotateForRecord(btn.dataset.annotate, btn.dataset.stem);
      }
    });
  });
  list.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rid = btn.dataset.delete;
      const name = btn.dataset.name || rid;
      if (
        !window.confirm(
          `确定删除记录「${name}」？\n\n将删除骨架数据、meta 与配套视频。\nannotations/ 目录下的标注文件不会删除。`
        )
      ) {
        return;
      }
      btn.disabled = true;
      try {
        const res = await fetch(recordApiUrl(rid), { method: "DELETE" });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || res.statusText || "删除失败");
        }
        if (currentRecordId === rid) {
          finishPlaybackSession();
          currentRecordId = null;
        }
        if (selectedPlaybackRecord?.recordId === rid) {
          selectedPlaybackRecord = null;
          updatePlaybackLoadButton();
        }
        await loadRecords();
      } catch (err) {
        window.alert(`删除失败：${err.message}`);
        btn.disabled = false;
      }
    });
  });
}

function renderPlaybackRecordsList(items) {
  const list = $("#session-list");
  const countEl = $("#playback-record-count");
  const filterQ = String($("#playback-record-filter")?.value || "")
    .trim()
    .toLowerCase();
  if (!items.length) {
    list.innerHTML = "<p class='hint playback-records-empty'>暂无记录（请先在采集页完成采集）</p>";
    if (countEl) countEl.textContent = "";
    selectedPlaybackRecord = null;
    updatePlaybackLoadButton();
    return;
  }
  const filtered = filterQ
    ? items.filter((s) => recordSearchBlob(s).includes(filterQ))
    : items;
  if (countEl) {
    countEl.textContent = filterQ
      ? `显示 ${filtered.length} / ${items.length} 条`
      : `共 ${items.length} 条`;
  }
  if (!filtered.length) {
    list.innerHTML = "<p class='hint playback-records-empty'>无匹配记录</p>";
    bindRecordListEvents(list);
    return;
  }
  const groups = new Map();
  for (const s of filtered) {
    const key =
      s.camera_slug ||
      s.camera_label ||
      (String(s.record_id || "").includes("/") ? String(s.record_id).split("/")[0] : "") ||
      "未分类";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }
  const keepId = selectedPlaybackRecord?.recordId || currentRecordId || "";
  const keys = [...groups.keys()].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  list.innerHTML = keys
    .map((key) => {
      const groupItems = groups.get(key);
      const total = groupItems.length;
      const limit = recordGroupVisibleLimits.get(key) ?? Math.min(RECORDS_VISIBLE_PER_GROUP, total);
      const visible = groupItems.slice(0, limit);
      const hidden = total - visible.length;
      const title = groupItems[0]?.camera_label || key;
      const groupReview = aggregateReviewStatus(groupItems);
      const groupReviewPill = renderReviewPill(groupReview);
      const rows = visible.map(renderRecordItem).join("");
      const openGroup =
        keys.length === 1 ||
        groupItems.some((s) => s.record_id === keepId) ||
        key === (keepId.includes("/") ? keepId.split("/")[0] : "");
      return `<details class="record-group" data-camera-slug="${recordItemEsc(key)}"${
        openGroup ? " open" : ""
      }>
          <summary class="record-group-title">
            <span class="record-group-label">机位 ${recordItemEsc(title)}</span>
            <span class="record-group-meta">
              ${groupReviewPill}
              <code>${recordItemEsc(key)}</code> · ${total} 条
            </span>
          </summary>
          <ul class="session-list">${rows}</ul>
          ${
            hidden > 0
              ? `<button type="button" class="record-show-more link-btn" data-group-key="${recordItemEsc(key)}" data-group-total="${total}">展开其余 ${hidden} 条</button>`
              : ""
          }
        </details>`;
    })
    .join("");
  bindRecordListEvents(list);
  if (keepId) highlightPlaybackRecordInList(keepId);
}

async function loadRecords({ quiet = false } = {}) {
  const list = $("#session-list");
  if (!quiet && !playbackRecordsCache.length) {
    list.innerHTML = "<p class='hint playback-records-empty'>加载记录中…</p>";
  }
  try {
    const res = await fetch("/api/records?summary=1");
    const items = await res.json();
    playbackRecordsCache = items;
    renderPlaybackRecordsList(items);
  } catch {
    list.innerHTML = "<p class='hint playback-records-empty'>无法加载列表</p>";
  }
}

function initPlaybackRecordFilter() {
  const input = $("#playback-record-filter");
  if (!input || input.dataset.bound) return;
  input.dataset.bound = "1";
  let t = null;
  input.addEventListener("input", () => {
    if (t) clearTimeout(t);
    t = setTimeout(() => renderPlaybackRecordsList(playbackRecordsCache), 200);
  });
}

async function loadSavedRecordVideo(recordId) {
  const url = recordApiUrl(recordId, "/video");

  if (playbackVideoObjectUrl) {
    URL.revokeObjectURL(playbackVideoObjectUrl);
    playbackVideoObjectUrl = null;
  }
  videoEl.src = url;
  videoEl.style.display = "block";
  videoEl.load();

  return new Promise((resolve) => {
    const onReady = () => {
      videoEl.removeEventListener("loadedmetadata", onReady);
      videoEl.removeEventListener("error", onErr);
      resolve(true);
    };
    const onErr = () => {
      videoEl.removeEventListener("loadedmetadata", onReady);
      videoEl.removeEventListener("error", onErr);
      resolve(false);
    };
    if (videoEl.readyState >= 1) {
      resolve(true);
      return;
    }
    videoEl.addEventListener("loadedmetadata", onReady);
    videoEl.addEventListener("error", onErr);
  });
}

async function startVideoPlayback(hintPrefix = "") {
  try {
    await videoEl.play();
    cancelAnimationFrame(rafId);
    tickPoseFrameIdx = -1;
    resetPlaybackCollisionTracker();
    tick();
    if (hintPrefix) setPlaybackInfo(`${hintPrefix}正在播放…`);
    return true;
  } catch (err) {
    setPlaybackInfo(`${hintPrefix}视频已加载，请点击播放或视频控件（${err.message}）`);
    redrawCurrentFrame();
    return false;
  }
}

async function openRecordReplay(recordId, displayName = "", jsonFileName = "", expectVideo = false) {
  tabs.forEach((b) => b.classList.toggle("active", b.dataset.tab === "playback"));
  Object.values(panels).forEach((p) => p.classList.remove("active"));
  panels.playback.classList.add("active");
  const exportLink = $("#playback-export-xlsx");
  if (exportLink) {
    if (recordId) {
      exportLink.href = recordApiUrl(recordId, "/export.xlsx");
      exportLink.download = `${recordId}_skeleton.xlsx`;
      exportLink.classList.remove("hidden");
    } else {
      exportLink.classList.add("hidden");
    }
  }
  await cleanupPlaybackVideo();
  clearVideoElement();
  currentRecordId = recordId;
  highlightPlaybackRecordInList(recordId);
  resetFrameFetchState();
  const manifestUrl = recordApiUrl(recordId, "/manifest.json");
  const poseRes = await fetch(manifestUrl);
  if (!poseRes.ok) {
    const fallbackUrl = recordApiUrl(recordId, "/pose.json");
    const fallback = await fetch(fallbackUrl);
    if (!fallback.ok) {
      throw new Error(
        `无法加载骨架记录（manifest ${poseRes.status} / pose ${fallback.status}）\n${manifestUrl}`
      );
    }
    poseData = await fallback.json();
  } else {
    const ct = poseRes.headers.get("content-type") || "";
    if (!ct.includes("json")) {
      throw new Error(`骨架接口返回非 JSON（${poseRes.status} ${ct}）\n${manifestUrl}`);
    }
    poseData = await poseRes.json();
  }
  await buildFrameIndex(recordId);
  await prefetchFrameChunk(1, FRAME_CHUNK_SIZE);
  if (!annotationBoxes.length) {
    try {
      const annRes = await fetch(recordApiUrl(recordId, "/annotation.json"));
      if (annRes.ok) {
        loadAnnotationBoxesFromData(await annRes.json());
      }
    } catch {
      /* 无独立标注文件时忽略 */
    }
  }
  await loadPlaybackEvents(recordId);
  const collisionHint =
    annotationBoxes.length && !collisionPersistedAtCollect()
      ? " · 已加载标注，回放时将实时计算碰撞"
      : "";
  $("#playback-video").value = "";
  const label = displayName || recordId;
  const jsonFile = jsonFileName || poseData?.pose_file || `${recordId}/manifest.json`;
  const storageHint = (poseData?.schema || 1) >= 2 ? " · Parquet" : "";
  const baseHint = `【${label}】${jsonFile}（${poseData.frame_count ?? 0} 帧${storageHint}）`;

  const videoLoaded = await loadSavedRecordVideo(recordId);
  if (playbackEvents.length) {
    await beginEventReview();
  }
  if (videoLoaded) {
    const { frameW, frameH } = getVideoFrameSize();
    const f0 = frameByTime[0];
    let hint = `${baseHint}${collisionHint} · 已加载配套视频 ${frameW}×${frameH}。`;
    if (f0 && (f0.w !== frameW || f0.h !== frameH)) {
      hint += ` JSON 推理 ${f0.w}×${f0.h}，将自动对齐。`;
    }
    if (playbackEvents.length) {
      hint += " · 已定位待复核事件，用「标为真 · 下一条」或 Y 键快速复核";
    }
    setPlaybackInfo(hint);
    redrawCurrentFrame();
    if (!playbackEvents.length) {
      await startVideoPlayback("");
    }
    return;
  }

  if (expectVideo) {
    setPlaybackInfo(`${baseHint} · 未找到已保存视频（可能采集时关闭了保存）。可上传替换或仅播放骨骼。`);
  } else {
    setPlaybackInfo(`${baseHint} · 无配套视频，可上传或仅播放骨骼。`);
  }
  redrawCurrentFrame();
}
