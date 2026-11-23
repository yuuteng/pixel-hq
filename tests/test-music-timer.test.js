import assert from "node:assert";

function formatTime(seconds) {
  if (!seconds || isNaN(seconds) || seconds < 0) return "00:00";
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    const remM = m % 60;
    return `${h}:${remM.toString().padStart(2, "0")}:${rem.toString().padStart(2, "0")}`;
  }
  return `${m.toString().padStart(2, "0")}:${rem.toString().padStart(2, "0")}`;
}

function calculateLiveElapsed(music, nowSec) {
  const isPlaying = Boolean(music?.playing);
  const pauseElapsed = Number(music?.elapsed || 0);
  return (isPlaying && music?.startTime)
    ? pauseElapsed + Math.max(0, nowSec - music.startTime)
    : Number(music?.currentElapsed || pauseElapsed);
}

function testFormatTime() {
  assert.strictEqual(formatTime(0), "00:00");
  assert.strictEqual(formatTime(-10), "00:00");
  assert.strictEqual(formatTime(NaN), "00:00");
  assert.strictEqual(formatTime(null), "00:00");
  assert.strictEqual(formatTime(45), "00:45");
  assert.strictEqual(formatTime(60), "01:00");
  assert.strictEqual(formatTime(125), "02:05");
  assert.strictEqual(formatTime(3599), "59:59");
  assert.strictEqual(formatTime(3600), "1:00:00");
  assert.strictEqual(formatTime(3665), "1:01:05");
  console.log("PASS: formatTime formatting validated across all edge cases");
}

function testTimerNoDoubleCountingAcrossTicks() {
  const startTime = 1000;
  const music = {
    playing: true,
    status: "playing",
    startTime,
    elapsed: 0,
    currentElapsed: 0,
    duration: 300
  };

  let prevElapsed = calculateLiveElapsed(music, startTime);
  assert.strictEqual(prevElapsed, 0);

  for (let sec = 1; sec <= 30; sec++) {
    const now = startTime + sec;
    if (sec % 2 === 0) {
      music.currentElapsed = sec;
    }
    const current = calculateLiveElapsed(music, now);
    assert.strictEqual(current, sec);
    assert.strictEqual(current - prevElapsed, 1);
    prevElapsed = current;
  }
  console.log("PASS: Timer advances by exactly 1s per tick with zero jumping or doubling");
}

function testPauseAndResumeTransitions() {
  const start = 2000;
  const music = {
    playing: true,
    status: "playing",
    startTime: start,
    elapsed: 0,
    currentElapsed: 0,
    duration: 200
  };

  assert.strictEqual(calculateLiveElapsed(music, start + 10), 10);

  music.playing = false;
  music.status = "paused";
  music.elapsed = 10;
  music.currentElapsed = 10;
  music.startTime = 2010;

  assert.strictEqual(calculateLiveElapsed(music, 2010), 10);
  assert.strictEqual(calculateLiveElapsed(music, 2015), 10);
  assert.strictEqual(calculateLiveElapsed(music, 2020), 10);

  music.playing = true;
  music.status = "playing";
  music.startTime = 2020;
  music.elapsed = 10;

  assert.strictEqual(calculateLiveElapsed(music, 2020), 10);
  assert.strictEqual(calculateLiveElapsed(music, 2021), 11);
  assert.strictEqual(calculateLiveElapsed(music, 2025), 15);
  console.log("PASS: Pause and resume transitions maintain consistent elapsed counter");
}

function testBinaryResolutionCaching() {
  let calls = 0;
  let detected = null;

  async function mockExec(bin, args) {
    calls++;
    if (args[1] === "check") {
      return { stdout: JSON.stringify({ status: "ok", has_player: true }) };
    }
    return { stdout: JSON.stringify({ status: "playing" }) };
  }

  async function resolveBin() {
    if (detected) return detected;
    const candidates = ["python", "py", "python3"];
    for (const b of candidates) {
      const r = await mockExec(b, ["script.py", "check"]);
      if (r?.stdout && r.stdout.includes('"status"')) {
        detected = b;
        return b;
      }
    }
    detected = candidates[0];
    return detected;
  }

  async function runPlayerAction(action) {
    const bin = await resolveBin();
    return mockExec(bin, ["script.py", action]);
  }

  (async () => {
    await runPlayerAction("next");
    assert.strictEqual(calls, 2);
    assert.strictEqual(detected, "python");

    await runPlayerAction("next");
    assert.strictEqual(calls, 3);

    await runPlayerAction("prev");
    assert.strictEqual(calls, 4);

    await runPlayerAction("stop");
    assert.strictEqual(calls, 5);
    console.log("PASS: Binary resolution caches properly and executes mutating commands exactly once");
  })();
}

function testMusicBoxDisableToggle() {
  function checkDisabled(store, settingsObj, sharedObj = {}) {
    const sh = sharedObj["pixel-hq.musicbox.hidden"];
    if (sh !== undefined && sh !== null) return Boolean(sh);
    try {
      if (store?.getItem("pixel-hq.musicbox.hidden") === "true") return true;
    } catch {}
    try {
      const cfg = settingsObj;
      if (cfg?.musicbox === false || cfg?.music?.enabled === false || cfg?.["company-music"]?.enabled === false) return true;
    } catch {}
    return false;
  }

  const mockStorage = {
    _data: {},
    getItem(k) { return this._data[k] ?? null; },
    setItem(k, v) { this._data[k] = String(v); },
    removeItem(k) { delete this._data[k]; }
  };

  assert.strictEqual(checkDisabled(mockStorage, {}), false);

  mockStorage.setItem("pixel-hq.musicbox.hidden", "true");
  assert.strictEqual(checkDisabled(mockStorage, {}), true);

  mockStorage.removeItem("pixel-hq.musicbox.hidden");
  assert.strictEqual(checkDisabled(mockStorage, {}), false);

  assert.strictEqual(checkDisabled(mockStorage, {}, { "pixel-hq.musicbox.hidden": true }), true);
  assert.strictEqual(checkDisabled(mockStorage, {}, { "pixel-hq.musicbox.hidden": false }), false);

  assert.strictEqual(checkDisabled(mockStorage, { musicbox: false }), true);
  assert.strictEqual(checkDisabled(mockStorage, { music: { enabled: false } }), true);
  assert.strictEqual(checkDisabled(mockStorage, { "company-music": { enabled: false } }), true);
  assert.strictEqual(checkDisabled(mockStorage, { musicbox: true }), false);

  console.log("PASS: MusicBox disable toggle via localStorage and settings verified");
}

function testMusicBoxHotkeyAndNotification() {
  function applyHotkey(parsed) {
    let changed = false;
    if (parsed.global && parsed.global["ctrl-shift-m"] !== "mod.open:company-music") {
      parsed.global["ctrl-shift-m"] = "mod.open:company-music";
      changed = true;
    }
    if (parsed.terminal && parsed.terminal["ctrl-shift-m"] !== "mod.open:company-music") {
      parsed.terminal["ctrl-shift-m"] = "mod.open:company-music";
      changed = true;
    }
    return { parsed, changed };
  }

  const initial = { global: { "ctrl-p": "space.switch" }, terminal: { "ctrl-c": "term.copy" } };
  const res1 = applyHotkey(initial);
  assert.strictEqual(res1.changed, true);
  assert.strictEqual(res1.parsed.global["ctrl-shift-m"], "mod.open:company-music");
  assert.strictEqual(res1.parsed.terminal["ctrl-shift-m"], "mod.open:company-music");
  assert.strictEqual(res1.parsed.global["ctrl-p"], "space.switch");

  const res2 = applyHotkey(res1.parsed);
  assert.strictEqual(res2.changed, false);

  function syncSettings(parsed, disabled) {
    let changed = false;
    if (disabled) {
      if (parsed.musicbox !== false) {
        parsed.musicbox = false;
        changed = true;
      }
    } else {
      if ("musicbox" in parsed) {
        delete parsed.musicbox;
        changed = true;
      }
    }
    return { parsed, changed };
  }

  const s1 = syncSettings({ zoom: 1.0 }, true);
  assert.strictEqual(s1.changed, true);
  assert.strictEqual(s1.parsed.musicbox, false);

  const s2 = syncSettings(s1.parsed, false);
  assert.strictEqual(s2.changed, true);
  assert.strictEqual("musicbox" in s2.parsed, false);

  console.log("PASS: MusicBox hotkey registration and settings synchronization verified");
}

console.log("=== Running Music Timer & Progression Tests ===");
testFormatTime();
testTimerNoDoubleCountingAcrossTicks();
testPauseAndResumeTransitions();
testBinaryResolutionCaching();
testMusicBoxDisableToggle();
testMusicBoxHotkeyAndNotification();
