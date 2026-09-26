/* Optional displacement of the overlay only. Keep the polynomial and taper
 * in sync with lens_solver/calibration.py. No camera pixels are resampled. */
(function(root) {
    'use strict';
    function delta(model, u, v) {
        const b = model.bounds;
        let weight = 1;
        for (const [x, lo, hi] of [[u, b[0], b[2]], [v, b[1], b[3]]]) {
            const t = Math.min(1, Math.max(0, lo-x, x-hi) / 0.15);
            weight *= 1-t*t*(3-2*t);
        }
        const t = Math.min(1, Math.max(0, Math.hypot(u, v)-1) / 0.15);
        weight *= 1-t*t*(3-2*t);
        if (!weight) return [0, 0];
        const basis = [1, u, v, u*u, u*v, v*v, u*u*u, u*u*v, u*v*v, v*v*v];
        const d = [0, 0];
        basis.forEach((value, i) => {
            d[0] += value*model.coefficients[i][0]*weight;
            d[1] += value*model.coefficients[i][1]*weight;
        });
        return d;
    }

    function compatible(model, geometry, size, context, uuid) {
        if (!model || ![1, 2].includes(model.version) || model.camera_uuid !== uuid
            || !Array.isArray(model.geometry) || model.geometry.length !== (model.version === 2 ? 10 : 8)) return false;
        // Version 1 predates lens curvature and catalogue-date correction.
        const savedGeometry = model.version === 1 && geometry.length === 10
            ? [...model.geometry, 0, 0] : model.geometry;
        for (const [saved, current] of [[savedGeometry, geometry], [model.image_size, size],
                                        [model.context, context]]) {
            if (!Array.isArray(saved) || saved.length !== current.length ||
                saved.some((n, i) => !Number.isFinite(n) || !Number.isFinite(current[i])
                    || Math.abs(n-current[i]) > 1e-8)) return false;
        }
        return Array.isArray(model.bounds) && model.bounds.length === 4
            && model.bounds.every(n => Number.isFinite(n) && Math.abs(n) <= 3)
            && model.bounds[2]-model.bounds[0] >= 0.15 && model.bounds[3]-model.bounds[1] >= 0.15
            && Array.isArray(model.coefficients) && model.coefficients.length === 10
            && model.coefficients.every(row => Array.isArray(row) && row.length === 2
                && row.every(n => Number.isFinite(n) && Math.abs(n) <= 1)) && safe(model);
    }

    function safe(model) {
        // Also check imported camera metadata, which may bypass our Save endpoint.
        const b = model.bounds, step = 1e-5;
        for (let i = 0; i < 49; i++) for (let j = 0; j < 49; j++) {
            const u = b[0]-0.15+(b[2]-b[0]+0.3)*i/48;
            const v = b[1]-0.15+(b[3]-b[1]+0.3)*j/48;
            if (Math.hypot(...delta(model, u, v)) > 0.06) return false;
            const left = delta(model, u-step, v), right = delta(model, u+step, v);
            const up = delta(model, u, v-step), down = delta(model, u, v+step);
            if (Math.hypot(right[0]-left[0], right[1]-left[1], down[0]-up[0], down[1]-up[1])
                / (2*step) >= 0.45) return false;
        }
        return true;
    }

    function install(sky, model) {
        // The page reuses its sky instance. Always restore the base projection
        // before toggling or replacing a model so corrections cannot accumulate.
        if (sky.calibrationProjection) {
            sky.azel2xy = sky.projection.azel2xy = sky.calibrationProjection.forward;
            sky.projection.xy2azel = sky.calibrationProjection.inverse;
        }
        if (!model) return;
        const forward = sky.azel2xy;
        const inverse = sky.projection.xy2azel;
        sky.calibrationProjection = {forward, inverse};
        sky.azel2xy = sky.projection.azel2xy = function(az, el, w, h, unclipped) {
            const p = forward.call(this, az, el, w, h, unclipped);
            if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) return p;
            const r = h/2;
            const d = delta(model, (p.x-w/2)/r, (p.y-h/2)/r);
            p.x += d[0]*r;
            p.y += d[1]*r;
            return p;
        };
        sky.projection.xy2azel = function(x, y, w, h) {
            const r = h/2, target = [(x-w/2)/r, (y-h/2)/r];
            if (!target.every(Number.isFinite)) return undefined;
            let u = target[0], v = target[1];
            // Server validation bounds the displacement gradient below 0.45,
            // so this fixed-point inverse converges even across the taper.
            // Orthographic rims need extra precision to remain inside the lens.
            for (let i = 0; i < 40; i++) {
                const d = delta(model, u, v);
                const nu = target[0]-d[0], nv = target[1]-d[1];
                if (Math.hypot(nu-u, nv-v) < 1e-14) {
                    return inverse.call(this, w/2+nu*r, h/2+nv*r, w, h);
                }
                u = nu; v = nv;
            }
            return undefined;
        };
    }
    function maskImage(sky, mask, size, binning, geometry) {
        if (sky.unmaskedDraw) sky.drawImmediate = sky.unmaskedDraw;
        sky.positionCardinalLabel = undefined;
        if (!Array.isArray(size) || size.length !== 2 || !size.every(n => Number.isFinite(n) && n > 0)
            || !Array.isArray(geometry) || geometry.length !== 3 || !geometry.every(Number.isFinite) || geometry[0] <= 0) return;
        const reference = geometry[0]/2;
        const bounds = [(-size[0]/2-geometry[1])/reference, (-size[1]/2+geometry[2])/reference,
                        (size[0]/2-geometry[1])/reference, (size[1]/2+geometry[2])/reference];
        let circle;
        // Labels are direction cues: keep their whole text inside the photo and
        // its opaque mask, even when the reference circle extends beyond either.
        // Normalized bounds also follow full-resolution downloads and resizes.
        sky.positionCardinalLabel = function(x, y, width, height) {
            const s = this.tall/2, mx = this.wide/2, my = this.tall/2;
            const hx = width/2+2, hy = height/2+2;
            const left = Math.max(0, mx+bounds[0]*s)+hx, right = Math.min(this.wide, mx+bounds[2]*s)-hx;
            const top = Math.max(0, my+bounds[1]*s)+hy, bottom = Math.min(this.tall, my+bounds[3]*s)-hy;
            if (left > right || top > bottom) return;
            let px = Math.max(left, Math.min(right, x+width/2));
            let py = Math.max(top, Math.min(bottom, y-height/2));
            if (circle) {
                const cx = mx+circle[0]*s, cy = my+circle[1]*s;
                const radius = circle[2]*s-Math.hypot(hx, hy);
                const ax = Math.max(left, Math.min(right, cx)), ay = Math.max(top, Math.min(bottom, cy));
                if (radius <= 0 || Math.hypot(ax-cx, ay-cy) > radius) return;
                if (Math.hypot(px-cx, py-cy) > radius) {
                    // Intersect a segment from a visible anchor with the circle;
                    // the whole segment also stays in the rectangular image.
                    const dx = px-ax, dy = py-ay, d2 = dx*dx+dy*dy;
                    const dot = (ax-cx)*dx+(ay-cy)*dy;
                    const t = (-dot+Math.sqrt(Math.max(0, dot*dot-d2*((ax-cx)**2+(ay-cy)**2-radius*radius))))/d2;
                    px = ax+t*dx; py = ay+t*dy;
                }
            }
            return [px-width/2, py+height/2];
        };
        if (!Array.isArray(mask) || mask.length !== 8 || !mask.every(Number.isFinite)
            || !Number.isInteger(binning) || binning <= 0 || mask[0] <= 0 || mask[3] <= 0) return;
        const [diameter, ox, oy, percent, top, right, bottom, left] = mask;
        const scale = percent/100, width = size[0]-left-right, height = size[1]-top-bottom;
        if (width <= 0 || height <= 0 || [top, right, bottom, left].some(n => n < 0)) return;
        // Circle masking happens in the cropped image, before scale and borders.
        // Work in photo coordinates, independently of the solved optical axis.
        const cx = left+width/2+Math.trunc(ox/binning)*scale;
        const cy = top+height/2-Math.trunc(oy/binning)*scale;
        const radius = Math.trunc(diameter/(2*binning))*scale;
        if (radius <= 0 || ![cx, cy, radius].every(Number.isFinite)) return;
        const x = (cx-size[0]/2-geometry[1])/reference;
        const y = (cy-size[1]/2+geometry[2])/reference;
        const r = radius/reference;
        circle = [x, y, r];
        const draw = sky.drawImmediate;
        sky.unmaskedDraw = draw;
        // Clip every draw, including refreshes and full-resolution downloads.
        // Neither the projection nor the learned correction is changed.
        sky.drawImmediate = function(...args) {
            const c = this.ctx;
            if (!c || this.tall <= 0 || this.wide <= 0) return draw.apply(this, args);
            // Clear outside the new clip too, e.g. after an alignment edit.
            c.clearRect(0, 0, this.wide, this.tall);
            c.save();
            c.beginPath();
            c.arc(this.wide/2+x*this.tall/2, this.tall/2+y*this.tall/2,
                r*this.tall/2, 0, 2*Math.PI);
            c.clip();
            try { return draw.apply(this, args); }
            finally { c.restore(); }
        };
    }
    const api = {delta, compatible, install, maskImage};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.VirtualSkyCalibration = api;
})(typeof window !== 'undefined' ? window : globalThis);
