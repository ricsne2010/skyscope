// The start-up splash's light show over the Project Moon Pi badge (the badge itself never moves), the same
// effect as the M.O.S.S. dash splash:
//   - a lens flare runs along the red swoosh, with faint ghost rings across the badge, and bursts into a
//     starburst at the swoosh's tip
//   - the stars in the blue ring twinkle
//   - the lander's engine flames flicker
//   - a band of light sweeps across the white rings and the lettering, like light on polished metal
// Where everything is comes from <logo>.fx.json, .fx-sheen.png and .fx-flame.png beside the logo, made by
// make_splash_fx.py (in the Project Moon Pi brand kit, _brand/animations). Everything is drawn once up front; each frame only adds those pieces onto the badge.
// Where the browser allows, it runs in a worker of its own (this same file), so the map loading alongside it
// can't make it stutter.
"use strict";

const SplashFX = (() => {
  const FLARE = [0.3, 2.1];     // seconds: the flare runs along the swoosh
  const BURST = [2.1, 3.0];     // the starburst at the tip
  const SHEEN = [2.5, 3.7];     // the light band across the rings and lettering
  const WARM = [255, 236, 200]; // flare and sheen light
  const BLUE = [120, 190, 255]; // engine glow
  const PAD = 0.14;             // room around the badge (a share of its width) so the starburst isn't cut off

  const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const ease = (x) => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };
  const bump = (t, [a, b]) => (a < t && t < b ? Math.sin(Math.PI * (t - a) / (b - a)) : 0);

  function canvas(w, h, draw) {
    w = Math.max(1, Math.ceil(w)); h = Math.max(1, Math.ceil(h));
    const c = typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(w, h) : document.createElement("canvas");
    c.width = w; c.height = h;
    draw(c.getContext("2d"), c.width, c.height);
    return c;
  }

  async function load(src) {
    const r = await fetch(src);
    if (!r.ok) throw new Error(`couldn't load ${src}`);
    return createImageBitmap(await r.blob());
  }

  // A soft round glow, for adding onto the picture.
  function glow(r, colour, falloff = 2.2) {
    return canvas(2 * r, 2 * r, (g, w) => {
      const grad = g.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
      for (let i = 0; i <= 8; i++) grad.addColorStop(i / 8, rgb(colour, (1 - i / 8) ** falloff));
      g.fillStyle = grad; g.fillRect(0, 0, w, w);
    });
  }

  // A faint ring (a lens 'ghost'): bright at its rim, dark inside.
  function ring(r, colour, width) {
    return canvas(2 * r + 4, 2 * r + 4, (g, w) => {
      const grad = g.createRadialGradient(w / 2, w / 2, Math.max(0, r - width), w / 2, w / 2, r);
      grad.addColorStop(0, rgb(colour, 0)); grad.addColorStop(1, rgb(colour, 1));
      g.fillStyle = grad;
      g.beginPath(); g.arc(w / 2, w / 2, r, 0, 2 * Math.PI); g.fill();
    });
  }

  // A long thin horizontal streak: the flare's anamorphic flash.
  function streak(len, h, colour) {
    return canvas(len, h, (g, w, hh) => {
      g.translate(w / 2, hh / 2); g.scale(1, hh / w);
      const grad = g.createRadialGradient(0, 0, 0, 0, 0, w / 2);
      for (let i = 0; i <= 8; i++) grad.addColorStop(i / 8, rgb(colour, (1 - i / 8) ** 3));
      g.fillStyle = grad; g.fillRect(-w / 2, -w / 2, w, w);
    });
  }

  // A starburst: thin rays of different lengths around a bright centre.
  function burst(r, colour, rays = 12) {
    let seed = 7;
    const rnd = (a, b) => { seed = (seed * 16807) % 2147483647; return a + (b - a) * (seed / 2147483647); };
    return canvas(4 * r, 4 * r, (g, w) => {
      const c = w / 2;
      g.globalCompositeOperation = "lighter"; g.lineCap = "round";
      for (let i = 0; i < rays; i++) {
        const a = 2 * Math.PI * i / rays + rnd(-0.08, 0.08);
        const ln = r * 2 * (i % 2 === 0 ? 1 : rnd(0.45, 0.7));
        for (const [lw, k] of [[3.5, 0.25], [2, 0.5], [1, 1]]) {
          g.strokeStyle = rgb(colour, k); g.lineWidth = lw;
          g.beginPath(); g.moveTo(c, c); g.lineTo(c + ln * Math.cos(a), c + ln * Math.sin(a)); g.stroke();
        }
      }
      g.drawImage(glow(0.6 * r, colour, 1.6), c - 0.6 * r, c - 0.6 * r);
    });
  }

  // A four-point star twinkle.
  function sparkle(size, colour) {
    const n = Math.max(6, size * 8);
    return canvas(n, n, (g, w) => {
      const c = w / 2;
      g.globalCompositeOperation = "lighter";
      for (const [lw, k] of [[3, 0.35], [1, 1]]) {
        g.strokeStyle = rgb(colour, k); g.lineWidth = lw;
        g.beginPath(); g.moveTo(0, c); g.lineTo(w, c); g.moveTo(c, 0); g.lineTo(c, w); g.stroke();
      }
      g.drawImage(glow(w * 0.22, colour, 1.4), c - w * 0.22, c - w * 0.22);
    });
  }

  // The part of a mask picture inside box [x, y, w, h], tinted: lit where the mask is white.
  function tinted(mask, [x, y, w, h], colour) {
    return canvas(w, h, (g) => {
      g.drawImage(mask, x, y, w, h, 0, 0, w, h);
      g.globalCompositeOperation = "multiply";
      g.fillStyle = rgb(colour); g.fillRect(0, 0, w, h);
    });
  }

  class Show {
    constructor(logo, fx, sheenMask, flameMask) {
      this.logo = logo;
      this.fx = fx;
      const R = this.R = fx.radius;
      this.cum = [0];
      for (let i = 1; i < fx.path.length; i++) {
        const [a, b] = [fx.path[i - 1], fx.path[i]];
        this.cum.push(this.cum[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1]));
      }
      let seed = 11;
      const rnd = (a, b) => { seed = (seed * 16807) % 2147483647; return a + (b - a) * (seed / 2147483647); };
      this.stars = fx.stars.map(([x, y, s]) => ({ x, y, size: Math.max(1, Math.round(s)), phase: rnd(0, 6.28), speed: rnd(1.6, 3.2) }));
      this.sparkles = {};
      for (const s of this.stars) this.sparkles[s.size] ||= sparkle(s.size, [255, 250, 235]);

      this.sheen = tinted(sheenMask, fx.sheen_box, WARM);
      this.flame = tinted(flameMask, fx.flame_box, [170, 215, 255]);
      // the light band for the sheen: a soft stripe leaning right (the light comes from the upper left)
      const bh = fx.sheen_box[3], bw = 0.5 * R;
      this.band = canvas(bw + bh * 0.45 + 1, bh, (g) => {
        g.setTransform(1, 0, -0.45, 1, 0.45 * bh, 0);
        const grad = g.createLinearGradient(0, 0, bw, 0);
        for (let i = 0; i <= 8; i++) grad.addColorStop(i / 8, rgb([255, 255, 255], (1 - Math.abs(2 * i / 8 - 1)) ** 2.2));
        g.fillStyle = grad; g.fillRect(0, 0, bw, bh);
      });
      this.strip = canvas(this.sheen.width, this.sheen.height, () => {});

      this.core = glow(0.16 * R, WARM, 1.8);
      this.halo = glow(0.45 * R, [110, 90, 70], 2.5);
      this.streak = streak(1.6 * R, 0.05 * R, [200, 210, 255]);
      this.ghosts = [[ring(0.07 * R, [60, 90, 140], 4), -0.3], [glow(0.05 * R, [90, 60, 120]), -0.55],
                     [ring(0.13 * R, [50, 110, 90], 5), -0.75], [glow(0.03 * R, [120, 100, 60]), 0.4]];
      this.burst = burst(0.32 * R, [255, 240, 215]);
      this.jetGlow = glow(0.11 * R, BLUE, 1.6);
    }

    // The point a fraction f of the way along the swoosh path.
    along(f) {
      const d = f * this.cum[this.cum.length - 1], p = this.fx.path;
      for (let i = 1; i < this.cum.length; i++) {
        if (this.cum[i] >= d) {
          const u = (d - this.cum[i - 1]) / Math.max(1e-6, this.cum[i] - this.cum[i - 1]);
          return [p[i - 1][0] + (p[i][0] - p[i - 1][0]) * u, p[i - 1][1] + (p[i][1] - p[i - 1][1]) * u];
        }
      }
      return p[p.length - 1];
    }

    add(g, img, [x, y], k = 1, scale = 1, turn = 0) {
      if (k <= 0.01) return;
      g.save();
      g.globalAlpha = Math.min(1, k);
      g.translate(x, y); g.rotate(turn); g.scale(scale, scale);
      g.drawImage(img, -img.width / 2, -img.height / 2);
      g.restore();
    }

    // Draw every piece once, then the opening frame over it, so nothing is drawn for the first time mid-flare.
    warm(g, pad) {
      for (const t of [1, 2.4, 3.1]) this.draw(g, t, pad);
      g.globalCompositeOperation = "lighter";
      for (const img of [...this.ghosts.map(([gh]) => gh), this.core, this.halo, this.streak, this.burst, this.jetGlow,
                         ...Object.values(this.sparkles)]) {
        for (const scale of [0.6, 1, 1.2]) this.add(g, img, this.fx.centre, 0.02, scale, 0.3);
      }
      this.draw(g, 0, pad);
    }

    draw(g, t, pad) {
      const fx = this.fx;
      g.globalCompositeOperation = "source-over"; g.globalAlpha = 1;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, g.canvas.width, g.canvas.height);
      g.translate(pad, pad);
      g.drawImage(this.logo, 0, 0);
      g.globalCompositeOperation = "lighter";

      // engines: a flicker on the flames and a glow under each nozzle
      const flick = 0.45 + 0.25 * Math.sin(t * 23) * Math.sin(t * 7.3 + 1) + 0.15 * Math.sin(t * 41);
      g.globalAlpha = Math.max(0, Math.min(1, flick));
      g.drawImage(this.flame, fx.flame_box[0], fx.flame_box[1]);
      fx.jets.forEach(([x, y], i) => this.add(g, this.jetGlow, [x, y], 0.35 + 0.25 * Math.sin(t * 19 + i * 2.1)));

      // stars: each glints now and then
      for (const s of this.stars) {
        const v = Math.sin(t * s.speed + s.phase);
        if (v > 0.55) this.add(g, this.sparkles[s.size], [s.x, s.y], (v - 0.55) / 0.45);
      }

      // the flare along the swoosh, its ghosts mirrored through the badge's centre
      if (FLARE[0] < t && t < FLARE[1] + 0.25) {
        const p = this.along(ease((t - FLARE[0]) / (FLARE[1] - FLARE[0])));
        const k = Math.min(1, (t - FLARE[0]) / 0.25) * (t < FLARE[1] ? 1 : 1 - (t - FLARE[1]) / 0.25);
        this.add(g, this.halo, p, 0.6 * k);
        this.add(g, this.streak, p, 0.7 * k);
        this.add(g, this.core, p, k);
        const [cx, cy] = fx.centre;
        for (const [ghost, s] of this.ghosts) {      // fading where they'd leave the badge
          const q = [cx + (p[0] - cx) * s, cy + (p[1] - cy) * s];
          const out = Math.hypot(q[0] - cx, q[1] - cy) / this.R;
          this.add(g, ghost, q, 0.8 * k * Math.max(0, Math.min(1, (0.85 - out) / 0.25)));
        }
      }

      // the starburst at the tip
      const b = bump(t, BURST);
      if (b) {
        const u = (t - BURST[0]) / (BURST[1] - BURST[0]);
        this.add(g, this.burst, fx.tip, b, 0.6 + 0.6 * u, -25 * u * Math.PI / 180);
        this.add(g, this.core, fx.tip, b);
      }

      // the sheen: the light band crossing the rings and lettering, left to right
      if (SHEEN[0] < t && t < SHEEN[1]) {
        const u = ease((t - SHEEN[0]) / (SHEEN[1] - SHEEN[0]));
        const s = this.strip.getContext("2d"), [sx, sy, sw] = fx.sheen_box;
        s.globalCompositeOperation = "source-over";
        s.fillStyle = "#000"; s.fillRect(0, 0, this.strip.width, this.strip.height);
        s.drawImage(this.band, -this.band.width + u * (sw + this.band.width), 0);
        s.globalCompositeOperation = "multiply";      // light only the strip under the band
        s.drawImage(this.sheen, 0, 0);
        g.globalAlpha = 0.85;
        g.drawImage(this.strip, sx, sy);
      }
      g.globalAlpha = 1;
    }
  }

  // Draw the logo onto canvas `target` and play the light show on it, calling done() once the flare and sheen
  // are over (the flames and stars carry on until stop()). Without the effect files the logo is shown still.
  async function run(target, base, still, done) {
    const g = target.getContext("2d");
    const logo = await load(`${base}.png`);
    const pad = Math.round(PAD * logo.width);
    target.width = logo.width + 2 * pad; target.height = logo.height + 2 * pad;
    g.drawImage(logo, pad, pad);
    if (still) return done();
    let show;
    try {
      const [fx, sheen, flame] = await Promise.all([
        fetch(`${base}.fx.json`).then((r) => r.json()), load(`${base}.fx-sheen.png`), load(`${base}.fx-flame.png`)]);
      show = new Show(logo, fx, sheen, flame);
    } catch (e) {
      console.warn("splash effect off:", e.message);
      return done();
    }
    const next = self.requestAnimationFrame
      ? (f) => requestAnimationFrame(f) : (f) => setTimeout(() => f(performance.now()), 16);
    show.warm(g, pad);                               // pay each piece's one-off first-draw cost before the clock starts
    const start = performance.now();
    let finished = false;
    const frame = (now) => {
      if (stopped) return;
      const t = (now - start) / 1000;
      show.draw(g, t, pad);
      if (!finished && t > SHEEN[1] + 0.2) { finished = true; done(); }
      next(frame);
    };
    next(frame);
  }

  let stopped = false, worker = null;
  const here = typeof document !== "undefined" && document.currentScript && document.currentScript.src;

  // Play on the page's canvas; resolves when the flare and sheen are over. Reduced motion: the logo, still.
  function play(target, base) {
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const url = new URL(base, location.href).href;
    if (!still && here && target.transferControlToOffscreen && typeof Worker !== "undefined") {
      try {
        worker = new Worker(here);
        const off = target.transferControlToOffscreen();
        return new Promise((done) => {
          worker.onmessage = () => done();
          worker.onerror = (e) => { console.warn("splash worker:", e.message); done(); };
          worker.postMessage({ canvas: off, base: url }, [off]);
        });
      } catch (e) {
        console.warn("splash worker:", e.message);   // fall back to drawing here
      }
    }
    return new Promise((done, fail) => run(target, url, still, done).catch(fail));
  }

  function stop() {
    stopped = true;
    if (worker) worker.terminate();
  }

  // Inside the worker: wait for the canvas, then run.
  if (typeof document === "undefined") {
    self.onmessage = (e) => run(e.data.canvas, e.data.base, false, () => self.postMessage("done"))
      .catch((err) => { console.warn("splash:", err.message); self.postMessage("done"); });
  }

  return { play, stop };
})();
