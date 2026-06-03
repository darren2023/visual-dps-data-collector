/** object-fit: contain 布局与标注坐标换算（与 visual-dps previewLayout.js 一致） */

function polygonMaxExtent(points) {
  let maxX = 0;
  let maxY = 0;
  if (!Array.isArray(points)) return { maxX, maxY };
  for (const pt of points) {
    if (!Array.isArray(pt) || pt.length < 2) continue;
    maxX = Math.max(maxX, Number(pt[0]) || 0);
    maxY = Math.max(maxY, Number(pt[1]) || 0);
  }
  return { maxX, maxY };
}

function computeContainLayout(containerW, containerH, frameW, frameH) {
  const cw = Math.max(1, containerW);
  const ch = Math.max(1, containerH);
  const fw = Math.max(1, frameW || cw);
  const fh = Math.max(1, frameH || ch);
  const scale = Math.min(cw / fw, ch / fh);
  const drawW = fw * scale;
  const drawH = fh * scale;
  return {
    scale,
    offsetX: (cw - drawW) / 2,
    offsetY: (ch - drawH) / 2,
    drawW,
    drawH,
    frameW: fw,
    frameH: fh,
  };
}

function isNormPolygonValid(normPts) {
  if (!Array.isArray(normPts) || normPts.length < 3) return false;
  for (const pt of normPts) {
    if (!Array.isArray(pt) || pt.length < 2) continue;
    const x = Number(pt[0]);
    const y = Number(pt[1]);
    if (x < -0.01 || x > 1.01 || y < -0.01 || y > 1.01) return false;
  }
  return true;
}

/** 将标注多边形换算到当前视频帧像素坐标（与后端 _scale_polygon_to_frame 对齐） */
function resolvePolygonFramePoints(polygon, normPolygon, annotationSize, frameW, frameH) {
  const tw = Math.max(1, frameW);
  const th = Math.max(1, frameH);
  if (isNormPolygonValid(normPolygon)) {
    return normPolygon.map(([x, y]) => [Number(x) * tw, Number(y) * th]);
  }
  if (!Array.isArray(polygon) || polygon.length < 3) return [];

  const { maxX, maxY } = polygonMaxExtent(polygon);
  const annW = Math.max(1, Number(annotationSize?.width) || tw);
  const annH = Math.max(1, Number(annotationSize?.height) || th);
  let sx = tw / annW;
  let sy = th / annH;
  if (maxX > annW * 1.05) sx = maxX > 0 ? tw / maxX : sx;
  if (maxY > annH * 1.05) sy = maxY > 0 ? th / maxY : sy;
  return polygon.map(([x, y]) => [Number(x) * sx, Number(y) * sy]);
}

function mapPointToDisplay(x, y, layout) {
  const frameW = Math.max(1, layout.frameW);
  const frameH = Math.max(1, layout.frameH);
  const sx = layout.drawW / frameW;
  const sy = layout.drawH / frameH;
  return [layout.offsetX + Number(x) * sx, layout.offsetY + Number(y) * sy];
}

function mapPointsToVideoFrame(points, normPolygon, annotationSize, frameW, frameH) {
  const norm = isNormPolygonValid(normPolygon) ? normPolygon : null;
  return resolvePolygonFramePoints(points, norm, annotationSize, frameW, frameH);
}

window.previewLayout = {
  computeContainLayout,
  isNormPolygonValid,
  resolvePolygonFramePoints,
  mapPointToDisplay,
  mapPointsToVideoFrame,
};
