/* =========================================================================
   Excavator Wind Run — Level 1 prototype
   ---------------------------------------------------------------------------
   A self-contained HTML-canvas game. No frameworks, no dependencies.

   Theme:
     - The player drives an excavator left-to-right through a construction
       corridor. The excavator's horizontal position is fixed; the world
       scrolls past it, which reads as forward travel.
     - A constant downward CROSSWIND pulls the excavator toward the grade
       (the ground).
     - The player applies UPWARD CORRECTION by holding Space / mouse / touch.
       P pauses/resumes, Escape ends the current run, R restarts.
     - Scaffolding hazards advance from the right with a gap to thread. Hitting
       a hazard, the grade, or the top of the corridor ends the run.
     - Score is the DISTANCE travelled (metres). The furthest run is kept in
       localStorage.

   The drawing palette is read from the shared CSS custom properties so the
   canvas stays consistent with the rest of the site's design system.
   ========================================================================= */
(function () {
  'use strict';

  var canvas = document.getElementById('game');
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext('2d');
  var stage = document.getElementById('stage');

  /* --- HUD / telemetry DOM handles --- */
  var el = {
    hudDist:  document.getElementById('hud-dist'),
    hudLevel: document.getElementById('hud-level'),
    msg:      document.getElementById('msg'),
    msgTitle: document.getElementById('msg-title'),
    msgSub:   document.getElementById('msg-sub'),
    // dashboard metrics: SCORE / SPEED / LEVEL / WIND (+ furthest run, status)
    mScore:   document.getElementById('m-score'),
    mSpeed:   document.getElementById('m-speed'),
    mLevel:   document.getElementById('m-level'),
    stBest:   document.getElementById('st-best'),
    stStatus: document.getElementById('st-status'),
    pause:    document.getElementById('pause'),
    end:      document.getElementById('end'),
    restart:  document.getElementById('restart')
  };

  /* --- Palette pulled from the shared design tokens --------------------- */
  function readPalette() {
    var cs = getComputedStyle(document.documentElement);
    var get = function (name, fallback) {
      var v = cs.getPropertyValue(name).trim();
      return v || fallback;
    };
    return {
      ink:     get('--ink', '#1A1A18'),
      muted:   get('--muted', '#6B675C'),
      faint:   get('--faint', '#8A867A'),
      surface: get('--surface', '#FCFBF7'),
      tint:    get('--surface-tint', '#F0EEE6'),
      alt:     get('--surface-alt', '#F4F2EA'),
      line:    get('--line', '#E5E2D9'),
      dash:    get('--dash', '#C4C0B5'),
      accent:  get('--accent', '#2563EB'),
      machine: get('--machine-yellow', '#F0C232')
    };
  }
  var PAL = readPalette();

  /* --- Best distance persistence --------------------------------------- */
  var BEST_KEY = 'nbdf.excavator.best';
  function loadBest() {
    try { return parseInt(localStorage.getItem(BEST_KEY), 10) || 0; }
    catch (e) { return 0; }
  }
  function saveBest(v) {
    try { localStorage.setItem(BEST_KEY, String(v)); } catch (e) {}
  }
  var best = loadBest();

  /* --- Tuning constants (world units = CSS pixels of the stage) ---------
     Physics are expressed per second and integrated with delta time so the
     game runs the same on 60Hz and 120Hz displays. */
  var PX_PER_M   = 16;      // pixels -> metres for the score readout
  var GRAVITY    = 1150;    // downward crosswind acceleration  (px/s^2)
  var LIFT       = 2550;    // upward correction while held     (px/s^2)
  var MAX_FALL   = 640;     // terminal downward speed          (px/s)
  var MAX_RISE   = -560;    // terminal upward speed            (px/s)
  var SPEED0     = 250;     // starting scroll speed            (px/s)
  var SPEED_MAX  = 470;     // capped scroll speed              (px/s)
  var SPEED_RAMP = 5.0;     // scroll speed gained per second   (px/s per s)
  var GROUND_H   = 26;      // height of the grade band
  var GAP_FRAC   = 0.42;    // hazard gap as a fraction of corridor height
  var GAP_MIN    = 132;     // smallest allowed gap             (px)
  var HAZ_W      = 46;      // hazard column width              (px)
  var HAZ_EVERY  = 300;     // horizontal distance between hazards (px)

  /* --- Mutable view metrics (set by resize) ---------------------------- */
  var W = 0, H = 0, dpr = 1;

  /* --- Game state ------------------------------------------------------- */
  var STATE = { READY: 'ready', RUN: 'run', PAUSED: 'paused', OVER: 'over' };
  var game;

  function newGame() {
    game = {
      state:    STATE.READY,
      endedBy:  null,      // 'crash' | 'stop' once state is OVER
      t:        0,         // elapsed run time (s)
      speed:    SPEED0,
      distPx:   0,
      thrust:   false,
      hazards:  [],        // { x, gapY, gapH, scored }
      sinceHaz: HAZ_EVERY, // spawn one immediately on first update
      // excavator
      ex: { x: 0, y: 0, vy: 0, w: 56, h: 34 },
      // parallax girders (background)
      girders: [],
      shake:    0
    };
    layoutExcavator();
    seedGirders();
    updateTelemetry();
  }

  function layoutExcavator() {
    game.ex.x = Math.round(W * 0.24);
    game.ex.y = Math.round((H - GROUND_H) * 0.42);
    game.ex.vy = 0;
  }

  function seedGirders() {
    game.girders = [];
    var n = Math.ceil(W / 130) + 2;
    for (var i = 0; i < n; i++) {
      game.girders.push({ x: i * 130, h: 40 + (i % 3) * 22 });
    }
  }

  /* --- Canvas sizing (handles high-DPI for crisp lines) ----------------- */
  function resize() {
    var rect = stage.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(280, Math.round(rect.width));
    H = Math.max(200, Math.round(rect.height));
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if (!game) {
      newGame();
    } else if (game.state === STATE.READY) {
      // keep the idle excavator sensibly placed after a resize
      layoutExcavator();
      seedGirders();
    }
    render(); // repaint immediately so a resize never shows a blank frame
  }

  /* --- Hazard spawning -------------------------------------------------- */
  function spawnHazard() {
    var corridor = H - GROUND_H;
    var gapH = Math.max(GAP_MIN, corridor * GAP_FRAC);
    var margin = 24;
    var gapY = margin + Math.random() * (corridor - gapH - margin * 2);
    game.hazards.push({ x: W + HAZ_W, gapY: gapY, gapH: gapH, scored: false });
  }

  /* --- Collision: axis-aligned box vs box ------------------------------- */
  function overlaps(ax, ay, aw, ah, bx, by, bw, bh) {
    return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
  }

  /* --- Simulation step -------------------------------------------------- */
  function update(dt) {
    if (game.state !== STATE.RUN) return;

    game.t += dt;
    // ramp difficulty: the corridor scrolls faster the longer you survive
    game.speed = Math.min(SPEED_MAX, SPEED0 + SPEED_RAMP * game.t);

    var dx = game.speed * dt;
    game.distPx += dx;

    // vertical physics: constant downward wind, optional upward correction
    var ex = game.ex;
    ex.vy += GRAVITY * dt;
    if (game.thrust) ex.vy -= LIFT * dt;
    ex.vy = Math.max(MAX_RISE, Math.min(MAX_FALL, ex.vy));
    ex.y += ex.vy * dt;

    // parallax background girders
    for (var g = 0; g < game.girders.length; g++) {
      var gi = game.girders[g];
      gi.x -= dx * 0.35;            // slower than foreground = depth
      if (gi.x < -14) gi.x += game.girders.length * 130;
    }

    // hazards: advance, score, recycle
    game.sinceHaz += dx;
    if (game.sinceHaz >= HAZ_EVERY) { spawnHazard(); game.sinceHaz = 0; }

    for (var i = game.hazards.length - 1; i >= 0; i--) {
      var hz = game.hazards[i];
      hz.x -= dx;
      if (!hz.scored && hz.x + HAZ_W < ex.x) { hz.scored = true; }
      if (hz.x + HAZ_W < -4) game.hazards.splice(i, 1);
    }

    if (game.shake > 0) game.shake = Math.max(0, game.shake - dt * 60);

    checkCollisions();
    updateTelemetry();
  }

  function checkCollisions() {
    var ex = game.ex;
    // hit-box is slightly inset from the drawn sprite for fairer play
    var pad = 6;
    var bx = ex.x - ex.w / 2 + pad;
    var by = ex.y - ex.h / 2 + pad;
    var bw = ex.w - pad * 2;
    var bh = ex.h - pad * 2;

    // grade (ground) and top of corridor
    if (by + bh >= H - GROUND_H) { return crash(); }
    if (by <= 0)                 { return crash(); }

    // scaffolding columns: top piece + bottom piece, leaving the gap
    for (var i = 0; i < game.hazards.length; i++) {
      var hz = game.hazards[i];
      var topH = hz.gapY;
      var botY = hz.gapY + hz.gapH;
      var botH = (H - GROUND_H) - botY;
      if (overlaps(bx, by, bw, bh, hz.x, 0, HAZ_W, topH) ||
          overlaps(bx, by, bw, bh, hz.x, botY, HAZ_W, botH)) {
        return crash();
      }
    }
  }

  function crash() {
    if (game.state !== STATE.RUN) return;
    game.state = STATE.OVER;
    game.endedBy = 'crash';
    game.shake = 10;
    var dist = metres();
    if (dist > best) { best = dist; saveBest(best); }
    showMessage('Off line',
      'The wind took you off the corridor at <span class="score">' + dist + ' m</span>. ' +
      'Furthest run: <span class="score">' + best + ' m</span>.<br>' +
      'Press <strong>Space</strong>, <strong>R</strong>, or tap to run again.');
    updateTelemetry();
  }

  /* --- End the run deliberately (Escape / End run button) --------------- */
  function endRun() {
    if (!game || (game.state !== STATE.RUN && game.state !== STATE.PAUSED)) return;
    game.state = STATE.OVER;
    game.endedBy = 'stop';
    game.thrust = false;
    var dist = metres();
    if (dist > best) { best = dist; saveBest(best); }
    showMessage('Run ended',
      'You covered <span class="score">' + dist + ' m</span>. ' +
      'Furthest run: <span class="score">' + best + ' m</span>.<br>' +
      'Press <strong>Space</strong>, <strong>R</strong>, or Restart to run again.');
    updateTelemetry();
  }

  /* --- Pause / resume (P key / Pause button). Freezes the simulation:
         update() early-returns for any state other than RUN, while render()
         keeps painting the frozen frame under the overlay. ---------------- */
  function pauseToggle() {
    if (!game) return;
    if (game.state === STATE.RUN) {
      game.state = STATE.PAUSED;
      game.thrust = false;
      showMessage('Paused',
        'Site work on hold at <span class="score">' + metres() + ' m</span>.<br>' +
        'Press <strong>P</strong> or Resume to continue.');
    } else if (game.state === STATE.PAUSED) {
      game.state = STATE.RUN;
      hideMessage();
    }
    updateTelemetry();
  }

  /* --- Distance helper -------------------------------------------------- */
  function metres() { return Math.floor(game.distPx / PX_PER_M); }

  /* --- Telemetry / HUD sync -------------------------------------------- */
  function updateTelemetry() {
    var d = metres();
    // SPEED: scroll speed (px/s) -> m/s -> km/h, a readable dashboard figure
    var kmh = Math.round((game.speed / PX_PER_M) * 3.6);

    if (el.hudDist)  el.hudDist.textContent  = d;     // on-canvas SCORE
    if (el.hudLevel) el.hudLevel.textContent = '01';
    if (el.mScore)   el.mScore.textContent   = d;     // dashboard: SCORE
    if (el.mSpeed)   el.mSpeed.textContent   = kmh;   // dashboard: SPEED
    if (el.mLevel)   el.mLevel.textContent   = '01';  // dashboard: LEVEL
    if (el.stBest)   el.stBest.textContent   = best;  // furthest run

    if (el.stStatus) {
      var running = game.state === STATE.RUN;
      var label =
        running                     ? 'On grade' :
        game.state === STATE.PAUSED ? 'Paused'   :
        game.state === STATE.OVER   ? (game.endedBy === 'stop' ? 'Ended' : 'Off line') :
                                      'Ready';
      // blue (live) dot while running, grey otherwise — same status component as home
      el.stStatus.innerHTML =
        '<span class="' + (running ? 'dot' : 'dot dot--wip') + '" aria-hidden="true"></span>' + label;
    }

    // keep the Pause button label in sync with the state
    if (el.pause) {
      var want = game.state === STATE.PAUSED ? 'Resume' : 'Pause';
      if (el.pause.textContent !== want) el.pause.textContent = want;
    }
  }

  /* --- Messages (start / crash) ---------------------------------------- */
  function showMessage(title, sub) {
    if (!el.msg) return;
    el.msgTitle.innerHTML = title;
    el.msgSub.innerHTML = sub;
    el.msg.classList.remove('is-hidden');
  }
  function hideMessage() { if (el.msg) el.msg.classList.add('is-hidden'); }

  /* =======================================================================
     Rendering
     ===================================================================== */
  function render() {
    var sx = 0, sy = 0;
    if (game.shake > 0) {
      sx = (Math.random() - 0.5) * game.shake;
      sy = (Math.random() - 0.5) * game.shake;
    }
    ctx.save();
    ctx.translate(sx, sy);

    drawBackground();
    drawHazards();
    drawGround();
    drawExcavator();

    ctx.restore();
  }

  function drawBackground() {
    // corridor surface
    ctx.fillStyle = PAL.surface;
    ctx.fillRect(-12, -12, W + 24, H + 24);

    // faint construction grid
    ctx.strokeStyle = PAL.line;
    ctx.lineWidth = 1;
    ctx.beginPath();
    var step = 44;
    for (var x = (-(game.distPx * 0.15) % step); x < W; x += step) {
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, H - GROUND_H);
    }
    for (var y = step; y < H - GROUND_H; y += step) {
      ctx.moveTo(0, Math.round(y) + 0.5);
      ctx.lineTo(W, Math.round(y) + 0.5);
    }
    ctx.stroke();

    // parallax girders rising from the grade (depth cue)
    ctx.fillStyle = PAL.tint;
    ctx.strokeStyle = PAL.dash;
    ctx.lineWidth = 2;
    for (var g = 0; g < game.girders.length; g++) {
      var gi = game.girders[g];
      var gx = Math.round(gi.x);
      var gh = gi.h;
      var gy = H - GROUND_H - gh;
      ctx.fillRect(gx, gy, 10, gh);
      ctx.strokeRect(gx + 0.5, gy + 0.5, 10, gh);
    }
  }

  function drawGround() {
    var gy = H - GROUND_H;
    // grade band
    ctx.fillStyle = PAL.ink;
    ctx.fillRect(0, gy, W, GROUND_H);
    // hatch on the grade
    ctx.strokeStyle = PAL.surface;
    ctx.globalAlpha = 0.30;
    ctx.lineWidth = 2;
    ctx.beginPath();
    var off = -(game.distPx % 18);
    for (var x = off; x < W + 18; x += 18) {
      ctx.moveTo(x, gy + GROUND_H);
      ctx.lineTo(x + 14, gy);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function drawHazards() {
    ctx.lineWidth = 2;
    for (var i = 0; i < game.hazards.length; i++) {
      var hz = game.hazards[i];
      var topH = hz.gapY;
      var botY = hz.gapY + hz.gapH;
      var botH = (H - GROUND_H) - botY;
      drawScaffold(hz.x, 0, HAZ_W, topH, true);
      drawScaffold(hz.x, botY, HAZ_W, botH, false);
    }
  }

  // A scaffold column with an X-braced lattice — echoes the card thumbnails.
  function drawScaffold(x, y, w, h, capBottom) {
    if (h <= 0) return;
    ctx.fillStyle = PAL.alt;
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = PAL.ink;
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);

    // diagonal cross-bracing
    ctx.strokeStyle = PAL.dash;
    ctx.lineWidth = 2;
    var seg = 34;
    ctx.beginPath();
    for (var sy = y; sy < y + h; sy += seg) {
      var sh = Math.min(seg, y + h - sy);
      ctx.moveTo(x + 2, sy + 2);       ctx.lineTo(x + w - 2, sy + sh - 2);
      ctx.moveTo(x + w - 2, sy + 2);   ctx.lineTo(x + 2, sy + sh - 2);
    }
    ctx.stroke();

    // a heavier cap beam at the gap edge
    ctx.fillStyle = PAL.ink;
    if (capBottom) ctx.fillRect(x - 3, y + h - 8, w + 6, 8);
    else           ctx.fillRect(x - 3, y, w + 6, 8);
  }

  // The excavator, seen from ABOVE (top-down): twin tracks along each side,
  // a construction-yellow house with rear counterweight, an offset cab with
  // a blue-accent window, and a boom + bucket reaching forward (right).
  // Nothing here should read as wings, a rocket, or an aircraft.
  function drawExcavator() {
    var ex = game.ex;
    var x = ex.x, y = ex.y, w = ex.w, h = ex.h;
    var left = x - w / 2;
    var top  = y - h / 2;

    // small yaw based on drift velocity — reads as steering into the wind
    var tilt = Math.max(-0.14, Math.min(0.14, ex.vy / 2000));

    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(tilt);
    ctx.translate(-x, -y);

    ctx.lineJoin = 'round';

    // --- twin tracks (left/right sides of the machine, top-down) ---------
    var trackH = 8;
    ctx.fillStyle = PAL.ink;
    roundRect(left, top, w, trackH, 4);              ctx.fill(); // far track
    roundRect(left, top + h - trackH, w, trackH, 4); ctx.fill(); // near track
    // tread notches, scrolled with distance so the tracks visibly roll
    ctx.strokeStyle = PAL.surface;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    var toff = -(game.distPx % 6);
    for (var tx = left + 3 + toff; tx < left + w - 2; tx += 6) {
      if (tx < left + 2) continue;
      ctx.moveTo(tx, top + 1.5);              ctx.lineTo(tx, top + trackH - 1.5);
      ctx.moveTo(tx, top + h - trackH + 1.5); ctx.lineTo(tx, top + h - 1.5);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;

    // --- house (rotating body) in construction yellow --------------------
    ctx.strokeStyle = PAL.ink;
    ctx.lineWidth = 2.5;
    ctx.fillStyle = PAL.machine;
    roundRect(left + 3, top + 6, w - 16, h - 12, 4); ctx.fill(); ctx.stroke();

    // rear counterweight (heavier ink block at the back)
    ctx.fillStyle = PAL.ink;
    roundRect(left + 3, top + 8, 6, h - 16, 3); ctx.fill();

    // --- cab, offset to one side near the front, blue glazing ------------
    ctx.fillStyle = PAL.surface;
    roundRect(left + w - 28, top + 8, 13, 11, 3); ctx.fill(); ctx.stroke();
    ctx.fillStyle = PAL.accent;
    roundRect(left + w - 26, top + 10, 9, 7, 2); ctx.fill();

    // --- boom + bucket reaching forward (to the right) -------------------
    var bx = left + w - 13;
    ctx.fillStyle = PAL.machine;
    ctx.lineWidth = 2.5;
    roundRect(bx, y - 3, 20, 6, 3); ctx.fill(); ctx.stroke();
    // bucket: a wide blade seen from above at the end of the boom
    ctx.fillStyle = PAL.ink;
    ctx.beginPath();
    ctx.moveTo(bx + 20, y - 7);
    ctx.lineTo(bx + 27, y - 8);
    ctx.lineTo(bx + 27, y + 8);
    ctx.lineTo(bx + 20, y + 7);
    ctx.closePath();
    ctx.fill();

    // --- correction cue: blue chevrons pushing upward while correcting ---
    if (game.thrust && game.state === STATE.RUN) {
      ctx.strokeStyle = PAL.accent;
      ctx.lineWidth = 2.5;
      ctx.globalAlpha = 0.9;
      ctx.beginPath();
      // two small up-chevrons trailing behind the machine
      ctx.moveTo(left - 14, y + 2); ctx.lineTo(left - 10, y - 3); ctx.lineTo(left - 6, y + 2);
      ctx.moveTo(left - 14, y + 9); ctx.lineTo(left - 10, y + 4); ctx.lineTo(left - 6, y + 9);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    ctx.restore();
  }

  function roundRect(x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /* =======================================================================
     Main loop
     ===================================================================== */
  var last = 0;
  function frame(now) {
    if (!last) last = now;
    var dt = (now - last) / 1000;
    last = now;
    if (dt > 0.05) dt = 0.05;   // clamp after tab switches / stalls
    update(dt);
    render();
    requestAnimationFrame(frame);
  }

  /* =======================================================================
     Input
     ===================================================================== */
  function startRun() {
    newGame();
    game.state = STATE.RUN;
    game.thrust = true;          // first press also lifts
    hideMessage();
    updateTelemetry();
  }

  // A single "press" either starts, restarts, or begins correcting.
  // While paused it does nothing — resume is explicit (P / Resume button).
  function press() {
    if (game.state === STATE.READY || game.state === STATE.OVER) {
      startRun();
    } else if (game.state === STATE.RUN) {
      game.thrust = true;
    }
  }
  function release() { if (game) game.thrust = false; }

  // Pointer (covers mouse + touch + pen)
  stage.addEventListener('pointerdown', function (e) {
    e.preventDefault();
    press();
  });
  window.addEventListener('pointerup', release);
  // if the pointer leaves the window mid-hold, stop thrusting
  window.addEventListener('pointercancel', release);
  window.addEventListener('blur', release);

  // Keyboard: Space = correct, P = pause/resume, Escape = end, R = restart.
  // Space is left alone while a button has focus so it still activates it.
  window.addEventListener('keydown', function (e) {
    var onButton = document.activeElement &&
                   document.activeElement.tagName === 'BUTTON';
    if (e.code === 'Space' || e.key === ' ') {
      if (onButton) return;
      e.preventDefault();
      if (!e.repeat) press();
    } else if (e.code === 'KeyP') {
      pauseToggle();
    } else if (e.code === 'Escape') {
      endRun();
    } else if (e.code === 'KeyR') {
      startRun();
    }
  });
  window.addEventListener('keyup', function (e) {
    if (e.code === 'Space' || e.key === ' ') release();
  });

  // Buttons: pause/resume, end run, restart
  if (el.pause)   el.pause.addEventListener('click', function () { pauseToggle(); });
  if (el.end)     el.end.addEventListener('click', function () { endRun(); });
  if (el.restart) el.restart.addEventListener('click', function () { startRun(); });

  // Re-read palette if the OS/theme changes (kept robust though page is light)
  window.addEventListener('resize', resize);

  /* --- Boot ------------------------------------------------------------- */
  resize();
  updateTelemetry();
  showMessage('Ready on site', 'Press <strong>Space</strong>, click, or tap to begin the run.');
  requestAnimationFrame(frame);
})();
