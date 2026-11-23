// A pixel-art office at night, seen from the front: a slate wall with two city windows and a server rack in the corner, a filing cabinet and a water cooler,
// a tiled floor lit by the windows. Everything snaps to a 4px grid and is built from rectangles; lights twinkle with native .loop().
import { div } from "gpui-kit";

const U = 4;
const snap = (v) => Math.round(v / U) * U;
const r = (x, y, w, h, c) => div().absolute().left(x).top(y).w(w).h(h).bg(c);
const rnd = (i) => { const v = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return v - Math.floor(v); };

function ellipse(cx, cy, rx, ry, c) {
  const out = [];
  for (let dy = -ry; dy < ry; dy += U) {
    const half = snap(rx * Math.sqrt(Math.max(0, 1 - ((dy + U / 2) / ry) ** 2)));
    if (half > 0) out.push(r(cx - half, cy + dy, half * 2, U, c));
  }
  return out;
}

// The tech corner on the wall: a server rack (drive bays, vents and fans, a glowing light on every unit) and a modern little desk with a monitor, keyboard and a mug.
const LIGHTS = ["#f4723a", "#f9d23c", "#8fcb4f", "#37c5d6", "#c678dd", "#f38ba8"];
const CODE = ["#cba6f7", "#89b4fa", "#a6e3a1", "#f9e2af", "#f5c2e7", "#94e2d5"]; // keyword, function, string, class, tag, type
function ledWall(x, w, base, isMusicPlaying = false, load = 0) {
  const o = [], top = 8, rw = w >= 64 ? snap(Math.min(28, w * 0.34)) : snap(w), rh = snap(Math.min(base - top, 80)), rt = base - rh;
  // Server rack: a cabinet with a lit top cap, a darker side, a plinth with feet, and units of three kinds.
  o.push(r(x - 2, rt - 2, rw + 4, rh + 2, "#0a0c1a"), r(x, rt, rw, rh, "#1a1f3d"), r(x + rw - 3, rt, 3, rh, "#12152c"), r(x, rt, 1, rh, "#2c3366"),
    r(x, rt, rw, 3, "#2c3366"), r(x + 3, rt + 4, rw - 8, 5, "#0a0d26"), r(x + 3, rt + 4, rw - 8, 1, "#3a4180"), r(x, base - 5, rw, 5, "#10132a"), r(x + 1, base - 1, 4, 1, "#3a3f66"), r(x + rw - 5, base - 1, 4, 1, "#3a3f66"));
  for (let c = 0; c < Math.floor((rw - 12) / 2); c++) { const h = 1 + Math.floor(rnd(c * 3 + 1) * 3); o.push(r(x + 5 + c * 2, rt + 8 - h, 1, h, c % 4 === 3 ? "#f9e2af" : "#a6e3a1")); }
  o.push(r(x - 6, rt - 4, rw + 12, rh + 4, "#a78bfa0b"));
  const units = Math.max(3, Math.floor((rh - 22) / 11));
  for (let k = 0; k < units; k++) {
    const uy = rt + 11 + k * 11, ux = x + 3, uw = rw - 8, kind = k % 4, ledC = LIGHTS[[2, 2, 0, 3, 2, 1][k % 6]];
    o.push(r(ux, uy, uw, 9, "#252b52"), r(ux, uy, uw, 1, "#3a4180"), r(ux, uy + 8, uw, 1, "#0f1226"));
    if (kind === 0) for (let b = 0; b < Math.min(3, Math.floor((uw - 10) / 5)); b++) o.push(r(ux + 8 + b * 5, uy + 2, 4, 5, "#323a70"), r(ux + 8 + b * 5, uy + 2, 4, 1, "#4a529a"));
    else if (kind === 1) for (let v = 0; v < Math.floor((uw - 10) / 3); v++) o.push(r(ux + 8 + v * 3, uy + 2, 1, 5, "#10132a"));
    else if (kind === 3) for (let q = 0; q < Math.floor((uw - 10) / 3); q++) {
      const pc = rnd(k * 9 + q) > 0.5 ? "#8fcb4f" : "#f4a23a", port = r(ux + 8 + q * 3, uy + 3, 2, 3, pc);
      o.push(r(ux + 8 + q * 3, uy + 6, 2, 1, "#10132a"), (q + k) % 3 === 0 ? port.loop("opacity", { from: 0.2, to: 1, period: 350 + ((q * 170 + k * 90) % 500), easing: "linear" }) : port);
    }
    else for (let f = 0; f < (uw >= 28 ? 2 : 1); f++) o.push(r(ux + 8 + f * 8, uy + 2, 5, 5, "#10132a"), r(ux + 9 + f * 8, uy + 3, 3, 3, "#323a70"));
    o.push(r(ux + 1, uy + 2, 5, 5, ledC + "33"));
    // One busy unit per sub-agent or shell job in the office: a green light blinking fast.
    const busy = k < load, led = r(ux + 2, uy + 3, 3, 3, busy ? "#a6e3a1" : ledC);
    o.push(busy ? led.loop("opacity", { from: 0.15, to: 1, period: 220 + ((k * 97) % 240), easing: "linear" })
      : k % 3 === 1 ? led.loop("opacity", { from: 0.25, to: 1, period: 700 + k * 230, easing: "ease-in-out" }) : led);
  }
  if (w >= 64) {
    const rx = x + 3, ry = rt - 11;
    o.push(
      r(rx, ry + 2, 18, 9, "#313244"),
      r(rx + 4, ry, 10, 2, "#45475a"),
      r(rx + 2, ry + 4, 4, 5, "#181825"),
      r(rx + 3, ry + 5, 2, 3, isMusicPlaying ? "#89b4fa" : "#45475a"),
      r(rx + 12, ry + 4, 4, 5, "#181825"),
      r(rx + 13, ry + 5, 2, 3, isMusicPlaying ? "#89b4fa" : "#45475a"),
      r(rx + 7, ry + 4, 4, 4, "#11111b"),
      r(rx + 15, ry - 3, 1, 3, "#89b4fa"),
      r(rx + 8, ry + 2, 2, 1, isMusicPlaying ? "#a6e3a1" : "#585b70")
    );
    if (isMusicPlaying) {
      o.push(
        r(rx + 4, ry - 6, 2, 2, "#cba6f7").loop("opacity", { from: 0.1, to: 1, period: 1400, easing: "ease-in-out" }),
        r(rx + 5, ry - 9, 1, 4, "#cba6f7").loop("opacity", { from: 0.1, to: 1, period: 1400, easing: "ease-in-out" }),
        r(rx + 11, ry - 9, 2, 2, "#89b4fa").loop("opacity", { from: 0.8, to: 0.1, period: 1700, easing: "ease-in-out" }),
        r(rx + 12, ry - 12, 1, 4, "#89b4fa").loop("opacity", { from: 0.8, to: 0.1, period: 1700, easing: "ease-in-out" }),
        r(rx + 17, ry - 5, 2, 2, "#f5c2e7").loop("opacity", { from: 0.2, to: 0.9, period: 1200, easing: "ease-in-out" })
      );
    }
  }
  if (w < 64) return o;
  // A little desk on the baseboard: a slim modern desk, and on it a monitor (code editor with a gutter, minimap and status bar), a keyboard, a mouse and a mug.
  const flick = (el, from, period) => el.loop("opacity", { from, to: 1, period, easing: "linear" });
  const mx = x + rw + 6, mw = snap(w - rw - 6), deskY = base - 17;
  const mh = Math.max(24, Math.min(deskY - top - 20, Math.round(mw * 0.8)));
  const my = deskY - 11 - mh, sy = my + mh + 3;
  o.push(r(mx - 4, my - 6, mw + 8, mh + 12, "#89b4fa0c"), // the screen's glow on the wall
    r(mx - 6, base, mw + 12, 2, "#0a0c1a66"),
    // a modern desk: a slim light top, thin dark legs with feet, a cable tray, a hanging white drawer and a glowing LED strip underneath
    r(mx - 5, deskY, mw + 10, 3, "#dfe3f2"), r(mx - 5, deskY, mw + 10, 1, "#f4f6fc"), r(mx - 5, deskY + 3, mw + 10, 1, "#9aa1c2"),
    r(mx - 5, base - 3, mw + 10, 3, "#6fe0f01a"), r(mx - 2, deskY + 4, 2, base - deskY - 4, "#2a2e4a"), r(mx + mw, deskY + 4, 2, base - deskY - 4, "#2a2e4a"),
    r(mx - 4, base - 1, 6, 1, "#2a2e4a"), r(mx + mw - 2, base - 1, 6, 1, "#2a2e4a"), r(mx + 1, deskY + 5, mw - 2, 2, "#1c2038"),
    r(mx + mw - 16, deskY + 7, 14, 8, "#c9cee4"), r(mx + mw - 16, deskY + 7, 14, 1, "#e6e9f5"), r(mx + mw - 13, deskY + 10, 8, 1, "#7e86ad"), r(mx + mw - 13, deskY + 13, 8, 1, "#7e86ad"),
    r(mx - 2, deskY + 4, mw + 4, 1, "#6fe0f0").loop("opacity", { from: 0.3, to: 1, period: 2600, easing: "ease-in-out" }), r(mx - 2, deskY + 4, mw + 4, 1, "#c4a0ff").loop("opacity", { from: 1, to: 0.3, period: 2600, easing: "ease-in-out" }),
    // the monitor: bezel with a light top edge, a neck and a foot
    r(mx - 3, my - 6, mw + 6, 2, "#f5c2e7").loop("opacity", { from: 0.2, to: 1, period: 2600, easing: "ease-in-out" }), r(mx - 3, my - 6, mw + 6, 2, "#89dceb").loop("opacity", { from: 1, to: 0.2, period: 2600, easing: "ease-in-out" }),
    r(mx - 3, my - 3, mw + 6, mh + 6, "#0a0c1a"), r(mx + Math.floor(mw / 2) - 1, my - 2, 2, 1, "#4a5090"), r(mx - 3, my - 3, mw + 6, 1, "#3a3f66"), r(mx, my, mw, mh, "#10143a"), r(mx, my + Math.floor(mh / 2), mw, Math.ceil(mh / 2), "#0e1233"),
    r(mx + Math.floor(mw / 2) - 2, sy, 4, deskY - sy, "#0a0c1a"), r(mx + Math.floor(mw / 2) - 9, deskY - 3, 18, 3, "#0a0c1a"), r(mx + Math.floor(mw / 2) - 9, deskY - 3, 18, 1, "#3a3f66"),
    // title bar with three dots and a tab
    r(mx, my, mw, 5, "#232a5c"), r(mx + 2, my + 1, 3, 3, "#f38ba8"), r(mx + 7, my + 1, 3, 3, "#f9e2af"), r(mx + 12, my + 1, 3, 3, "#a6e3a1"), r(mx + 18, my + 1, Math.min(14, mw - 40), 4, "#10143a"), flick(r(mx + mw - 12, my + 1, 9, 3, "#a6e3a1"), 0.35, 1000),
    // status bar
    r(mx, my + mh - 4, mw, 4, "#1d2250"), r(mx + 2, my + mh - 3, 8, 2, "#89b4fa"), flick(r(mx + 12, my + mh - 3, 6, 2, "#a6e3a1"), 0.3, 800), r(mx + mw - 9, my + mh - 3, 6, 2, "#f9e2af"),
    // keyboard, mouse, mug with steam
    r(mx + 3, deskY - 3, Math.min(mw - 16, 26), 3, "#2a2f4f"), r(mx + 3, deskY - 3, Math.min(mw - 16, 26), 1, "#f5c2e7").loop("opacity", { from: 0.3, to: 1, period: 2600, easing: "ease-in-out" }), r(mx + 3, deskY - 3, Math.min(mw - 16, 26), 1, "#89dceb").loop("opacity", { from: 1, to: 0.3, period: 2600, easing: "ease-in-out" }), r(mx + mw - 12, deskY - 2, 4, 2, "#aab4d6"),
    r(mx + mw - 6, deskY - 5, 5, 5, "#e8e2d0"), r(mx + mw - 1, deskY - 4, 2, 3, "#e8e2d0"), r(mx + mw - 5, deskY - 5, 3, 1, "#6b4430"),
    r(mx + mw - 5, deskY - 9, 1, 3, "#cdd6f4").loop("opacity", { from: 0, to: 0.7, period: 1600, easing: "ease-in-out" }), r(mx + mw - 3, deskY - 11, 1, 3, "#cdd6f4").loop("opacity", { from: 0.6, to: 0, period: 1900, easing: "ease-in-out" }));
  // The monitor shows a worker processing data: code on top with the lines being run shimmering, and under it a live log (finished batches in green,
  // the current one blinking amber, the text flickering as it streams), a progress bar with a blinking frontier and a throughput meter.
  const edH = Math.floor((mh - 15) * 0.42), tY = my + 8 + edH + 2, tH = my + mh - 5 - tY;
  if (tH >= 12) {
    o.push(r(mx, tY, mw, tH, "#080b22"), r(mx, tY, mw, 1, "#2a3270"));
    const logRows = Math.min(5, Math.floor((tH - 9) / 4));
    for (let l = 0; l < logRows; l++) {
      const y = tY + 3 + l * 4, cur = l === logRows - 1, wMax = Math.max(6, mw - 28), mwid = 5 + Math.floor(rnd(l * 5 + 2) * (wMax - 5));
      o.push(cur ? flick(r(mx + 2, y, 2, 2, "#f9e2af"), 0.1, 520) : r(mx + 2, y, 2, 2, "#a6e3a1"), r(mx + 6, y, 5, 2, "#4a529a"),
        flick(r(mx + 13, y, mwid, 2, cur ? "#e6e9f5" : "#7a84bd"), cur ? 0.25 : 0.55, cur ? 330 : 1100 + l * 370),
        r(mx + mw - 8, y, 5, 2, cur ? "#f9e2af" : "#94e2d5"));
    }
    const py = tY + tH - 5, segs = Math.floor((mw - 6 - 14) / 3), lit = Math.max(1, segs - 2);
    for (let q = 0; q < segs; q++) { const seg = r(mx + 3 + q * 3, py, 2, 2, q < lit ? "#a6e3a1" : "#1d2250"); o.push(q === lit - 1 ? flick(seg, 0.2, 600) : seg); }
    for (let t = 0; t < 4; t++) { const h = 2 + Math.floor(rnd(t * 3 + 5) * 3); o.push(flick(r(mx + mw - 14 + t * 3, py + 2 - h, 2, h, "#89b4fa"), 0.25, 380 + t * 170)); }
  }
  const rows = Math.floor(edH / 4), indents = [0, 1, 1, 2, 2, 1, 2, 0, 1, 2, 1, 0], right = mx + mw - 9;
  for (let row = 0; row < rows; row++) {
    const ry = my + 8 + row * 4;
    o.push(r(mx + 2, ry, 2, 2, "#3a3f66"));
    if (row === 2) o.push(r(mx + 5, ry - 1, mw - 10, 4, "#ffffff0b"));
    if (row % 5 === 4) continue;
    let cx = mx + 7 + indents[row % indents.length] * 4;
    for (let part = 0; part < 3; part++) {
      const pw = 4 + Math.floor(rnd(row * 7 + part * 3) * 11);
      if (cx + pw > right) break;
      o.push(r(cx, ry, pw, 2, CODE[Math.floor(rnd(row * 11 + part * 5 + 2) * CODE.length)]));
      cx += pw + 2;
    }
  }
  for (const [rr, per] of [[1, 1100], [3, 1500]]) if (rr < rows) o.push(flick(r(mx + 5, my + 7 + rr * 4, mw - 10, 4, "#a6e3a122"), 0.15, per));
  for (let m = 0; m < Math.floor(edH / 3); m++) o.push(r(mx + mw - 6, my + 8 + m * 3, 2 + Math.floor(rnd(m * 4 + 1) * 3), 1, "#4a529a"));
  o.push(r(mx + 7 + 4, my + 8 + Math.min(rows - 1, 3) * 4, 2, 2, "#cdd6f4").loop("opacity", { from: 0, to: 1, period: 900, easing: "ease-in-out" }));
  return o;
}

export const yHorizon = (H) => snap(snap(H) * 0.3); // where the wall ends and the floor begins

// The time of day from the local clock: the sky, the city, the sun or the moon and the light on the floor follow it.
const PHASES = {
  night: { sky: "#0e1226", city: "#161b36", pool: "#ffffff07", stars: true, body: "#d9cf9a" },
  dawn: { sky: "#3d2f5e", city: "#1f2342", pool: "#ffd9a00b", stars: false, body: "#fab387" },
  day: { sky: "#4f86c6", city: "#2d3d6b", pool: "#ffffff12", stars: false, body: "#f9e2af" },
  dusk: { sky: "#5a3358", city: "#22213f", pool: "#ffb38a0b", stars: false, body: "#fab387" },
};
export function phaseOf(date) {
  const h = date.getHours() + date.getMinutes() / 60;
  const name = h >= 5 && h < 7.5 ? "dawn" : h >= 7.5 && h < 17.5 ? "day" : h >= 17.5 && h < 20.5 ? "dusk" : "night";
  // How far the sun (5:00 to 20:30) or the moon (20:30 to 5:00) has crossed the sky, 0 to 1.
  const progress = name === "night" ? (((h - 20.5) + 24) % 24) / 8.5 : (h - 5) / 15.5;
  return { name, h, progress: Math.max(0, Math.min(1, progress)) };
}

// Where everything on the wall is, shared by the drawing and by the clickable spots over it (main.js).
export function sceneLayout(W, H) {
  W = snap(W); H = snap(H);
  const yH = yHorizon(H), base = yH - 8;
  const rackW = Math.max(64, Math.min(110, snap(W * 0.27))), rackX = W - rackW - 10;
  const rackCab = rackW >= 64 ? snap(Math.min(28, rackW * 0.34)) : snap(rackW), rackTop = base - snap(Math.min(base - 8, 80));
  const cw = rackX - 30, x0 = 38, usable = cw - 10 - x0;
  const two = usable >= 100;
  const gap = two ? Math.max(32, snap(usable * 0.26)) : 0;
  const wA = two ? snap((usable - gap) / 2) : usable, wB = usable - wA - gap;
  const winY = snap(yH * 0.1), winH = snap(yH * 0.58);
  const wins = [{ x: x0, w: snap(wA), seed: 1, moon: true }, ...(two ? [{ x: x0 + wA + gap, w: snap(wB), seed: 4, moon: false }] : [])].map((o) => ({ ...o, y: winY, h: winH }));
  const buildings = wins.flatMap((wn) => {
    const bw = snap(wn.w / 6);
    return Array.from({ length: 6 }, (_, i) => {
      const bh = snap(14 + rnd(i + wn.seed * 7) * wn.h * 0.5);
      return { x: wn.x + i * bw, y: wn.y + wn.h - bh, w: bw - 2, h: bh, i, seed: wn.seed };
    });
  });
  const cx = two ? x0 + wA + Math.floor(gap / 2) : snap(W * 0.5), cr = Math.min(14, Math.floor(gap / 2) - 2) || 14;
  const rr = Math.max(8, cr);
  const sign = gap >= 44 && base - 48 >= 88 ? { x: cx - 16, y: 48, w: 32, h: 32 } : null;
  // The board: a dot-matrix strip on the wall under the windows, between the plant and the water cooler, when there is room.
  const sill = winY + winH + 4, bx = x0 - 2, bw = cw - 8 - bx, bh = 16;
  const board = base - sill >= 30 && bw >= 96 ? { x: bx, y: snap(sill + Math.max(6, (base - sill - bh) / 2 - 4)), w: bw, h: bh } : null;
  return { W, H, yH, base, rackX, rackW, rackCab, rackTop, cw, wins, buildings, two, cx, cy: 26, rr, sign, board,
    cooler: { x: cw, y: base - 54, w: 20, h: 54 }, plant: { x: 0, y: base - 84, w: 36, h: 84 } };
}

// opts: { music, now (Date), spaces: [{ id, name, status, active }], needYou, load, shipped, droop }.
// A boolean is the old signature (music playing).
export function scene(W, H, opts = {}) {
  if (typeof opts === "boolean") opts = { music: opts };
  const Lo = sceneLayout(W, H);
  ({ W, H } = Lo);
  const { yH, base, wins, buildings, cx, cy, rr } = Lo;
  const now = opts.now ?? new Date();
  const ph = phaseOf(now), P = PHASES[ph.name];
  const L = [];

  // Back wall: slate, a lighter band, a dark skirting and a dark line under the ceiling.
  L.push(r(0, 0, W, yH, "#262a42"), r(0, 0, W, 4, "#161827"), r(0, yH - 32, W, 24, "#2c3150"), r(0, yH - 32, W, 4, "#363c5f"), r(0, base, W, 8, "#171a2c"));

  // Windows onto the city: the sky of the hour, stars at night, the sun or the moon crossing from the left window to the right.
  for (const wn of wins) {
    L.push(r(wn.x - 4, wn.y - 4, wn.w + 8, wn.h + 8, "#0c0e1c"), r(wn.x, wn.y, wn.w, wn.h, P.sky));
    if (P.stars) for (let i = 0; i < 6; i++) L.push(r(wn.x + 6 + (i % 4) * snap(wn.w / 4), wn.y + 6 + snap(rnd(i + wn.seed) * wn.h * 0.3), U, U, "#f5e9b0").loop("opacity", { from: 0.2, to: 0.9, period: 1500 + i * 400, easing: "ease-in-out" }));
  }
  {
    const span = wins.reduce((n, wn) => n + wn.w - 20, 0);
    let along = ph.progress * span;
    const wn = wins.find((w) => { if (along <= w.w - 20) return true; along -= w.w - 20; return false; }) ?? wins[wins.length - 1];
    const bx = snap(wn.x + 10 + Math.min(along, wn.w - 20)), by = snap(wn.y + 12 + (1 - Math.sin(Math.PI * ph.progress)) * wn.h * 0.3);
    L.push(...ellipse(bx, by, 8, 8, P.body));
    if (ph.name === "day") L.push(...ellipse(bx, by, 12, 12, "#f9e2af22"));
  }

  // The city: one building per space (in the order of the spaces list, as many as there are buildings). A space with an agent at
  // work is lit up, one that needs you blinks a red beacon on its roof, one that shipped shows a green one; the floor you are on
  // has a blue roof line. The other buildings keep a few lights at night.
  const spaceList = opts.spaces ?? [];
  for (const b of buildings) {
    const k = buildings.indexOf(b), sp = spaceList[k] ?? null, st = sp?.status ?? null;
    L.push(r(b.x, b.y, b.w, b.h, P.city));
    if (sp?.active) L.push(r(b.x, b.y, b.w, 2, "#89b4fa"));
    const rows = Math.max(1, Math.min(4, Math.floor((b.h - 6) / 10)));
    for (let q = 0; q < rows * 2; q++) {
      const lx = b.x + 4 + (q % 2) * 8, ly = b.y + 6 + Math.floor(q / 2) * 10;
      if (lx + U > b.x + b.w - 1) continue;
      const seed = rnd(q + b.i * 13 + b.seed * 5);
      const on = st === "working" ? seed > 0.2 : st === "blocked" ? seed > 0.5 : st ? q === 0 : P.stars ? seed > 0.65 : false;
      if (!on) continue;
      L.push(r(lx, ly, U, U, "#e0b94a").loop("opacity", { from: st === "working" ? 0.35 : 0.5, to: 1, period: st === "working" ? 700 + ((q * 137 + b.i * 61) % 600) : 2000 + q * 700, easing: "ease-in-out" }));
    }
    if (st === "blocked") L.push(r(b.x + Math.floor(b.w / 2) - 2, b.y - 4, 4, 4, "#f38ba8").loop("opacity", { from: 0.15, to: 1, period: 480, easing: "linear" }));
    else if (st === "done") L.push(r(b.x + Math.floor(b.w / 2) - 2, b.y - 4, 4, 4, "#a6e3a1"));
  }
  for (const wn of wins) {
    for (const f of [0.16, 0.5, 0.84]) for (let s = 0; s < wn.h / 4; s++) { const gx = wn.x + f * wn.w - s * 3; if (gx > wn.x + 2 && gx + 8 < wn.x + wn.w - 2) L.push(r(gx, wn.y + s * 4, 8, 4, "#ffffff0d")); }
    L.push(r(wn.x + wn.w / 2 - 2, wn.y, 4, wn.h, "#0c0e1c"), r(wn.x, wn.y + wn.h / 2 - 2, wn.w, 4, "#0c0e1c"), r(wn.x - 8, wn.y + wn.h + 4, wn.w + 16, 5, "#7e86ad"));
  }

  // The clock between the windows shows the time: an hour and a minute hand drawn in 2px steps.
  const hand = (len, ang, c, t) => {
    const o = [];
    for (let st = 1; st <= len; st += 2) o.push(r(Math.round(cx + Math.sin(ang) * st - t / 2), Math.round(cy - Math.cos(ang) * st - t / 2), t, t, c));
    return o;
  };
  const mins = now.getMinutes(), hrs = (now.getHours() % 12) + mins / 60;
  L.push(...ellipse(cx, cy, rr, rr, "#8e94b2"), ...ellipse(cx, cy, rr - 4, rr - 4, "#d8dcee"),
    ...hand(rr - 5, (mins / 60) * 2 * Math.PI, "#2a2d44", 2), ...hand(Math.max(3, rr - 8), (hrs / 12) * 2 * Math.PI, "#2a2d44", 3), r(cx - 2, cy - 2, 4, 4, "#c0424e"));

  // The sign under the clock: how many agents need you (red, blinking). Nothing when nobody does; the board has the rest.
  if (Lo.sign && (opts.needYou ?? 0) > 0) {
    const { x, y, w, h } = Lo.sign, n = opts.needYou;
    {
      L.push(r(x - 2, y - 2, w + 4, h + 4, "#f38ba8").loop("opacity", { from: 0.35, to: 1, period: 900, easing: "ease-in-out" }), r(x, y, w, h, "#3b1d2b"),
        div().absolute().left(x).top(y).w(w).h(h - 6).flex().items_center().justify_center().font_family("JetBrains Mono").font_bold().text_size(n > 9 ? 13 : 16).text_color("#f38ba8").child(n > 99 ? "99+" : String(n)),
        div().absolute().left(x).top(y + h - 11).w(w).h(9).flex().items_center().justify_center().font_family("JetBrains Mono").font_bold().text_size(6.5).text_color("#f5c2e7").child("NEED YOU"));
    }
  }

  // No room for the sign (a narrow office): the count rides on the clock as a small red badge instead.
  if (!Lo.sign && (opts.needYou ?? 0) > 0) {
    const n = opts.needYou, bx = cx + rr - 6, by = cy + rr - 8;
    L.push(r(bx, by, 12, 10, "#f38ba8").loop("opacity", { from: 0.4, to: 1, period: 900, easing: "ease-in-out" }),
      div().absolute().left(bx).top(by).w(12).h(10).flex().items_center().justify_center().font_family("JetBrains Mono").font_bold().text_size(7.5).text_color("#2a0f16").child(n > 9 ? "9+" : String(n)));
  }

  // The water cooler stands on the baseboard, left of the server rack; a bubble rises in its jug now and then.
  const cw = Lo.cw;
  L.push(r(cw + 2, base - 54, 16, 22, "#6fa8d6"), r(cw + 4, base - 52, 4, 10, "#a9d0ee"), r(cw, base - 32, 20, 32, "#b7bfd6"), r(cw, base - 32, 20, 4, "#d3d8ea"), r(cw + 8, base - 24, 4, 4, "#e8744f"),
    // Loop values are kept small and relative to a normally placed lane: Herdr doesn't scale loop values by the zoom, so a loop over
    // absolute wall heights drifts (at zoom 1.2 this bubble floated a jug's height above the cooler).
    div().absolute().left(cw + 10).top(base - 52).w(2).h(18).child(r(0, 16, 2, 2, "#e6f2fb").loop("top", { from: 16, to: 0, period: 2600, easing: "ease-in" })));

  // The plant in the left corner is a little potted tree that grows with the work shipped today: a sapling with one leafy crown,
  // then a new branch with its own cluster of leaves at 1, 4, 8, 13, 19 and 26 tasks, and pink blossoms from 30. While someone has
  // waited on you for a long time it droops: the branches sag and the leaves yellow.
  const shipped = Math.max(0, opts.shipped ?? 0), droop = Boolean(opts.droop);
  const bark = "#6b4a32", barkHi = "#8a6444";
  const dark = droop ? "#6e7a3a" : "#2f6e3b", mid = droop ? "#7d8a40" : "#3a8247", lite = droop ? "#a3a852" : "#5fb06b";
  const px = 6, sag = droop ? 3 : 0, tx = px + 12;
  // [from x, from y, tip x, tip y, crown size] relative to the pot's left edge and the baseboard; the first is the crown.
  const BRANCHES = [[tx, -40, tx + 1, -50, 3], [tx, -30, px + 1, -36, 2], [tx + 2, -33, px + 21, -39, 2], [tx, -42, px + 1, -50, 2],
    [tx + 2, -45, px + 22, -53, 2], [tx, -50, px + 5, -60, 2], [tx + 2, -52, px + 20, -63, 2]];
  const STEPS = [1, 4, 8, 13, 19, 26], grown = 1 + STEPS.filter((n) => shipped >= n).length;
  // the trunk, a touch thicker at the base
  L.push(r(tx, base - 40, 3, 22, bark), r(tx, base - 40, 1, 22, barkHi), r(tx - 1, base - 22, 5, 4, bark));
  const crowns = [];
  BRANCHES.slice(0, grown).forEach(([fx, fy, ex, ey, size], i) => {
    const ty = base + ey + (i ? sag * (i % 2 ? 1 : 2) : sag);
    // the branch: 2px steps from the trunk out to its tip
    if (i) {
      const n = Math.max(Math.abs(ex - fx), Math.abs(ey - fy)) / 2;
      for (let k = 0; k <= n; k++) L.push(r(Math.round(fx + ((ex - fx) * k) / n), Math.round(base + fy + ((ty - base - fy) * k) / n), 2, 2, bark));
    }
    crowns.push([ex, ty, size, i]);
  });
  // leafy clusters: a dark rounded blob, a mid layer and a few light leaves on top, bigger for the crown
  for (const [cxp, cyp, size, i] of crowns) {
    const w = size === 3 ? 16 : 11, h = size === 3 ? 12 : 9, x = cxp - Math.floor(w / 2), y = cyp - Math.floor(h / 2);
    L.push(r(x + 2, y, w - 4, h, dark), r(x, y + 2, w, h - 4, dark), r(x + 2, y + 1, w - 5, h - 4, mid), r(x + 1, y + 3, w - 4, h - 6, mid),
      r(x + 3, y + 1, 3, 2, lite), r(x + w - 6, y + 3, 3, 2, lite), r(x + 4 + (i % 3), y + h - 4, 2, 2, lite));
    if (shipped >= 30 && !droop) L.push(r(x + 2 + ((i * 5) % (w - 4)), y + 1 + (i % 2) * 3, 3, 3, "#f5c2e7").loop("opacity", { from: 0.55, to: 1, period: 1600 + i * 170, easing: "ease-in-out" }));
  }
  // the pot
  L.push(r(px + 2, base - 18, 24, 18, "#8a5a3c"), r(px, base - 18, 28, 4, "#a06c48"), r(px + 4, base - 14, 20, 1, "#6f472f"));

  // The tech corner, with the office's load on the rack.
  L.push(...ledWall(Lo.rackX, Lo.rackW, base, Boolean(opts.music), Math.max(0, opts.load ?? 0)));

  // Tiled floor: a dark base with a grid of 24px tiles, and a pool of window light under each window.
  L.push(r(0, yH, W, H - yH, "#242843"));
  for (let x = 0; x < W; x += 24) L.push(r(x, yH, 2, H - yH, "#1c1f36"));
  for (let y = yH + 4; y < H; y += 24) L.push(r(0, y, W, 2, "#1c1f36"));
  for (const wn of wins) for (let i = 0; i < 9; i++) L.push(r(wn.x + i * 6, yH + 8 + i * 8, Math.round(wn.w * 0.85), 8, P.pool));
  L.push(r(0, yH, 4, H - yH, "#0d0f1a"), r(W - 4, yH, 4, H - yH, "#0d0f1a"), r(0, H - 4, W, 4, "#0d0f1a"));

  return div().absolute().left(0).top(0).w(W).h(H).overflow_hidden().children(L);
}

// Where each desk stands: x as a fraction of the width, y of the floor. Two staggered columns.
export const SLOTS = [
  [0.27, 0.0], [0.74, 0.1], [0.27, 0.62], [0.74, 0.72], [0.27, 1.0], [0.74, 1.0],
];
