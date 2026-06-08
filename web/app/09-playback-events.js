/** 回放事件加载、定位与清除 */

/** 采集时是否已启用碰撞并落盘（有则信任存储字段，含空数组） */
function collisionPersistedAtCollect() {
  return !!(poseData?.collision?.enabled);
}

function frameUsesStoredCollisions(frame) {
  if (!collisionPersistedAtCollect() || !frame) return false;
  return (
    ("collisions" in frame || "alarm_collisions" in frame) &&
    (Array.isArray(frame.collisions) || Array.isArray(frame.alarm_collisions))
  );
}

async function collectAllFramesForPlayback(recordId) {
  if ((poseData?.schema || 1) < 2) {
    if (poseData?.frames?.length) {
      return poseData.frames.filter((f) => f && typeof f === "object");
    }
    return frameByTime.map((e) => e.frame).filter(Boolean);
  }
  const total = Number(poseData?.frame_count) || frameByTime.length;
  if (!recordId || total <= 0) return [];
  for (let from = 1; from <= total; from += FRAME_CHUNK_SIZE) {
    const to = Math.min(from + FRAME_CHUNK_SIZE - 1, total);
    await prefetchFrameChunk(from, to);
  }
  const frames = [];
  for (let i = 1; i <= total; i++) {
    const fr = frameCache.get(i);
    if (fr) frames.push(fr);
  }
  frames.sort((a, b) => (Number(a.frame_idx) || 0) - (Number(b.frame_idx) || 0));
  return frames;
}

/** 无采集碰撞落盘但有标注时，按帧扫描生成事件（方案一：仅回放侧） */
async function buildPlaybackEventsFromRealtime(recordId) {
  if (!annotationBoxes.length || collisionPersistedAtCollect()) return [];
  resetPlaybackCollisionTracker();
  const tracker = getPlaybackCollisionTracker();
  const frames = await collectAllFramesForPlayback(recordId);
  const events = [];
  for (const fr of frames) {
    const inferW = Number(fr.infer_width) || Number(poseData?.infer_width) || 640;
    const inferH = Number(fr.infer_height) || Number(poseData?.infer_height) || 480;
    const computed = tracker.update(fr, inferW, inferH);
    const ts = Number(fr.timestamp_sec) || 0;
    const fi = Number(fr.frame_idx) || 0;
    const sfi = Number(fr.source_frame_idx) || fi;
    const alarms = [...(computed.alarm_collisions || [])].map(String).filter(Boolean);
    const collisions = [...(computed.collisions || [])].map(String).filter(Boolean);
    if (alarms.length) {
      events.push({
        event_type: "alarm",
        frame_idx: fi,
        source_frame_idx: sfi,
        timestamp_sec: ts,
        box_tokens: alarms,
      });
    }
    const collOnly = collisions.filter((t) => !alarms.includes(t));
    if (collOnly.length) {
      events.push({
        event_type: "collision",
        frame_idx: fi,
        source_frame_idx: sfi,
        timestamp_sec: ts,
        box_tokens: collOnly,
      });
    }
  }
  events.sort((a, b) => a.timestamp_sec - b.timestamp_sec || a.frame_idx - b.frame_idx);
  return events;
}

async function loadPlaybackEvents(recordId = null) {
  playbackEvents = [];
  playbackEventsFromRealtime = false;
  activeEventKey = null;
  verifiedTrueKeys.clear();
  reviewBackKey = null;
  currentEventReviewStatus = "not_started";
  setEventReviewSaveStatus("");

  if (recordId) {
    try {
      const res = await fetch(recordApiUrl(recordId, "/events"));
      if (res.ok) {
        const body = await res.json();
        playbackEvents = Array.isArray(body.events) ? body.events : [];
        syncVerifiedKeysFromEvents(playbackEvents, body.event_review);
        currentEventReviewStatus =
          body.event_review_status ||
          (body.event_review?.status
            ? body.event_review.status
            : body.count === 0
              ? "no_collision"
              : body.event_review?.verified_true?.length || body.event_review?.updated_at
                ? "in_progress"
                : "not_started");
        if (body.count === 0 && currentRecordId) {
          patchPlaybackRecordReviewStatus(
            currentRecordId,
            currentEventReviewStatus,
            body.event_review_label || reviewStatusLabel(currentEventReviewStatus)
          );
        }
      }
    } catch {
      /* 忽略 */
    }
  } else if (poseData?.frames?.length) {
    playbackEvents = buildEventsFromFrames(poseData.frames);
  }

  const needRealtime =
    !playbackEvents.length && annotationBoxes.length > 0 && !collisionPersistedAtCollect();
  if (needRealtime) {
    playbackEvents = await buildPlaybackEventsFromRealtime(recordId);
    playbackEventsFromRealtime = playbackEvents.length > 0;
    resetPlaybackCollisionTracker();
  }

  applyVerifiedFlagsToEvents();
  renderEventReviewList();
}

async function seekToTimestamp(timeSec, frameIdx = null) {
  lastRenderedFrameIdx = -1;
  tickPoseFrameIdx = -1;
  resetPlaybackCollisionTracker();
  const t = Math.max(0, Number(timeSec) || 0);
  if (videoEl.duration && Number.isFinite(videoEl.duration) && videoEl.duration > 0) {
    videoEl.currentTime = Math.min(t, videoEl.duration);
    seekBar.value = String((videoEl.currentTime / videoEl.duration) * 1000);
    timeLabel.textContent = formatTime(videoEl.currentTime);
    await renderAtTime(videoEl.currentTime);
    return;
  }

  let hit = null;
  if (frameIdx != null) {
    hit = frameByTime.find((item) => item.frameIdx === frameIdx) || null;
  }
  if (!hit) hit = findFrameAt(t);
  if (hit) {
    await renderFrameEntry(hit);
    const idx = frameByTime.indexOf(hit);
    if (idx >= 0 && frameByTime.length) {
      seekBar.value = String((idx / frameByTime.length) * 1000);
      timeLabel.textContent = `${idx + 1}/${frameByTime.length}`;
    } else {
      timeLabel.textContent = formatTime(t);
    }
  }
}

async function seekToEvent(ev, { keepReviewBack = false } = {}) {
  if (!ev) return;
  activeEventKey = eventRowKey(ev);
  if (!keepReviewBack && reviewBackKey && activeEventKey === reviewBackKey) {
    reviewBackKey = null;
  }
  updateReviewDock();
  if ($("#event-review-list-details")?.open) renderEventReviewTable();
  renderEventMarkers();
  videoEl.pause();
  await seekToTimestamp(ev.timestamp_sec, ev.frame_idx);
}

function clearPlaybackEvents() {
  playbackEvents = [];
  playbackEventsFromRealtime = false;
  activeEventKey = null;
  verifiedTrueKeys.clear();
  reviewBackKey = null;
  if (eventReviewSaveTimer) {
    clearTimeout(eventReviewSaveTimer);
    eventReviewSaveTimer = null;
  }
  if (eventMarkersEl) eventMarkersEl.innerHTML = "";
  if (eventJumpList) eventJumpList.innerHTML = "";
  if (eventsPanel) eventsPanel.classList.add("hidden");
  if (eventCountLabel) eventCountLabel.textContent = "—";
  setEventReviewSaveStatus("");
}

function setPlaybackInfo(text) {
  $("#playback-info").textContent = text;
}
