/** 回放记录选中与 Tab 离开挂起 */
let selectedPlaybackRecord = null;

function updatePlaybackLoadButton() {
  const btn = document.getElementById("playback-load-record");
  if (btn) btn.disabled = !selectedPlaybackRecord?.recordId;
}

function selectPlaybackRecordItem(li) {
  if (!li?.dataset?.recordId) return;
  selectedPlaybackRecord = {
    recordId: li.dataset.recordId,
    displayName: li.dataset.displayName || li.dataset.recordId,
    poseFile: li.dataset.poseFile || "",
    hasVideo: li.dataset.hasVideo === "1",
  };
  document.querySelectorAll("#session-list .record-item").forEach((el) => {
    el.classList.toggle("record-item-selected", el === li);
  });
  updatePlaybackLoadButton();
}

function highlightPlaybackRecordInList(recordId) {
  if (!recordId) return;
  const li = document.querySelector(`#session-list .record-item[data-record-id="${CSS.escape(recordId)}"]`);
  if (li) selectPlaybackRecordItem(li);
}

function getPlaybackRecordSelection() {
  return selectedPlaybackRecord;
}

async function startPlaybackFromSelectedRecord() {
  const sel = getPlaybackRecordSelection();
  if (!sel?.recordId) {
    setPlaybackInfo("❌ 请先在下方列表点击选择一条记录");
    return;
  }
  await openRecordReplay(sel.recordId, sel.displayName, sel.poseFile, sel.hasVideo);
}

// --- 标签页 ---
/** 切离回放页：仅暂停，保留视频源、事件列表与画布叠加 */
function suspendPlaybackOnTabLeave() {
  stopPlayback();
}

/** 回到回放页：恢复导出链接、事件 UI 与当前帧叠加 */
function restorePlaybackPanelUi() {
  if (!poseData && !currentRecordId) return;
  const exportLink = $("#playback-export-xlsx");
  if (exportLink && currentRecordId) {
    exportLink.href = recordApiUrl(currentRecordId, "/export.xlsx");
    exportLink.download = `${currentRecordId}_skeleton.xlsx`;
    exportLink.classList.remove("hidden");
  }
  renderEventJumpList();
  renderEventMarkers();
  redrawCurrentFrame();
  if (currentRecordId && !videoEl.getAttribute("src")) {
    void loadSavedRecordVideo(currentRecordId);
  }
}
