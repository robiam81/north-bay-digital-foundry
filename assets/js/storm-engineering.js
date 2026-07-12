/* =========================================================================
   North Bay Digital Foundry — Storm Drainage Toolkit
   Pure engineering calculation layer (ES module).

   Rules for this module:
   • No DOM access, no localStorage, no event listeners.
   • Every exported function accepts a plain object (US customary units,
     documented per function) and returns an explicit result object:
       success → { isValid: true,  ...results }
       failure → { isValid: false, errors: [{ field, message }] }
   • Preliminary-design / screening methods only. Every result must be
     independently verified by a licensed professional engineer.

   REVIEWER FLAG — hydraulic coefficients in this module (weir/orifice
   coefficients, HDS-5 inlet-control constants, HEC-14 apron relations,
   Manning's n values) are representative textbook/FHWA defaults entered
   from reference material. Verify each against the cited source (HEC-22,
   HDS-5, HEC-14) before publishing — this is safety/liability-relevant
   content on a public page.
   ========================================================================= */

/**
 * @typedef {Object} FieldError
 * @property {string} field   Input field name the error applies to.
 * @property {string} message Human-readable message for display next to the field.
 */

/**
 * @typedef {Object} CalcFailure
 * @property {false} isValid
 * @property {FieldError[]} errors
 */

/* --- Physical constants (US customary) ---------------------------------- */
const GRAVITY = 32.174;      // gravitational acceleration, ft/s²
const SQFT_PER_ACRE = 43560; // ft² per acre (also cf per ac-ft of depth 1 ft)

/* --- Runtime guards ------------------------------------------------------ */
const MAX_MAGNITUDE = 1e6;   // overflow guard on inputs and results
const MIN_MAGNITUDE = 1e-4;  // underflow guard on non-zero inputs (flat storm slopes)

/**
 * Validate one numeric input and collect an error if it fails.
 *
 * @param {FieldError[]} errors Accumulator; an entry is pushed on failure.
 * @param {string} field    Field name reported back to the UI.
 * @param {*} value         Candidate value (anything; must be a finite number).
 * @param {string} label    Human label used in the message.
 * @param {Object} [opts]
 * @param {number} [opts.min]      Inclusive lower bound (default MIN_MAGNITUDE).
 * @param {number} [opts.max]      Inclusive upper bound (default MAX_MAGNITUDE).
 * @param {boolean} [opts.allowZero] Accept exactly zero (default false).
 * @returns {number} The validated number, or NaN when invalid.
 */
function requireNumber(errors, field, value, label, opts) {
  const o = opts || {};
  const min = typeof o.min === 'number' ? o.min : MIN_MAGNITUDE;
  const max = typeof o.max === 'number' ? o.max : MAX_MAGNITUDE;

  if (typeof value !== 'number' || !Number.isFinite(value)) {
    errors.push({ field, message: label + ' must be a number.' });
    return NaN;
  }
  if (value === 0 && o.allowZero) return 0;
  if (value < 0) {
    errors.push({ field, message: label + ' cannot be negative.' });
    return NaN;
  }
  if (value !== 0 && value < MIN_MAGNITUDE) {
    errors.push({ field, message: label + ' is below the computable range (min ' + MIN_MAGNITUDE + ').' });
    return NaN;
  }
  if (value < min) {
    errors.push({ field, message: label + ' must be at least ' + min + '.' });
    return NaN;
  }
  if (value > max) {
    errors.push({ field, message: label + ' exceeds the computable range (max ' + max + ').' });
    return NaN;
  }
  return value;
}

/**
 * Parse a comma-separated list of non-negative numbers from a text field.
 *
 * @param {FieldError[]} errors Accumulator; an entry is pushed on failure.
 * @param {string} field  Field name reported back to the UI.
 * @param {*} value       Raw string, e.g. "10, 20, 30".
 * @param {string} label  Human label used in the message.
 * @param {Object} [opts]
 * @param {number} [opts.max] Inclusive upper bound per entry (default MAX_MAGNITUDE).
 * @param {boolean} [opts.allowZero] Accept zero entries (default false).
 * @returns {number[]|null} Parsed values, or null when invalid.
 */
function requireNumberList(errors, field, value, label, opts) {
  if (typeof value !== 'string' || value.trim() === '') {
    errors.push({ field, message: label + ' is required.' });
    return null;
  }
  const parts = value.split(',').map((s) => s.trim()).filter((s) => s !== '');
  if (parts.length === 0 || parts.length > 12) {
    errors.push({ field, message: label + ' must list 1–12 comma-separated values.' });
    return null;
  }
  const out = [];
  for (const part of parts) {
    const collected = [];
    const v = requireNumber(collected, field, Number(part), label, opts);
    if (collected.length) {
      errors.push({ field, message: label + ': "' + part + '" — ' + collected[0].message });
      return null;
    }
    out.push(v);
  }
  return out;
}

/**
 * @param {FieldError[]} errors
 * @returns {CalcFailure}
 */
function failure(errors) {
  return { isValid: false, errors };
}

/**
 * Guard computed numeric results against overflow / non-finite values.
 *
 * @param {Object.<string, number>} results Keyed numeric results.
 * @param {string} field Field to attach the error to if the guard trips.
 * @returns {CalcFailure|null} A failure object, or null when all results are sane.
 */
function guardResults(results, field) {
  for (const key of Object.keys(results)) {
    const v = results[key];
    if (!Number.isFinite(v) || Math.abs(v) > MAX_MAGNITUDE) {
      return failure([{ field, message: 'Result exceeds the computable range — check input magnitudes.' }]);
    }
  }
  return null;
}

/* --- Circular-section geometry (θ = wetted central angle, radians) ------ */

/** @param {number} theta @param {number} dFt @returns {number} flow area, ft² */
function circArea(theta, dFt) {
  return dFt * dFt / 8 * (theta - Math.sin(theta));
}

/** @param {number} theta @param {number} dFt @returns {number} hydraulic radius, ft */
function circHydraulicRadius(theta, dFt) {
  return dFt / 4 * (1 - Math.sin(theta) / theta);
}

/** @param {number} theta @param {number} dFt @returns {number} flow depth, ft */
function circDepth(theta, dFt) {
  return dFt / 2 * (1 - Math.cos(theta / 2));
}

/**
 * Critical depth in a circular section (bisection on the Froude condition
 * Q²·T / (g·A³) = 1). Returns the full diameter when flow is critical or
 * supercritical at the full section (HDS-5 caps dc at D).
 *
 * @param {number} Q   Discharge, cfs.
 * @param {number} dFt Diameter, ft.
 * @returns {{dcFt: number, acFt2: number}}
 */
function circularCriticalDepth(Q, dFt) {
  const froudeExcess = (theta) => {
    const A = circArea(theta, dFt);
    const T = dFt * Math.sin(theta / 2); // top width
    return Q * Q * T - GRAVITY * Math.pow(A, 3);
  };
  let lo = 1e-3;                 // f(lo) > 0 (tiny area)
  let hi = 2 * Math.PI - 1e-3;   // f(hi) < 0 when a subcritical root exists
  if (froudeExcess(hi) > 0) {
    return { dcFt: dFt, acFt2: Math.PI * dFt * dFt / 4 };
  }
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2;
    if (froudeExcess(mid) > 0) lo = mid; else hi = mid;
  }
  const theta = (lo + hi) / 2;
  return { dcFt: circDepth(theta, dFt), acFt2: circArea(theta, dFt) };
}

/* =========================================================================
   1 · Rational Method peak flow (with optional Kirpich Tc)
   ========================================================================= */

/**
 * Rational Method peak runoff, with time of concentration either entered
 * directly or estimated with the Kirpich equation.
 *
 * Equations:
 *   Q (cfs)  = C · i · A            (C —, i in/hr, A acres)
 *   Tc (min) = 0.0078 · L^0.77 · S^−0.385   (Kirpich; L ft, S ft/ft)
 *
 * Rainfall intensity i must come from the local IDF curve at the design
 * return period and Tc — IDF curves are regional and are not hardcoded
 * here. Reference: Rational Method per FHWA HEC-22 Ch. 3; Kirpich (1940).
 *
 * @param {Object} input
 * @param {'direct'|'kirpich'} input.mode Tc entry mode.
 * @param {number} input.runoffC        Runoff coefficient C (0.05–1.0).
 * @param {number} input.areaAcres      Drainage area A, acres (> 0; small sites).
 * @param {number} input.intensityInHr  Rainfall intensity i, in/hr (> 0).
 * @param {number} [input.tcMin]        Time of concentration, min (mode 'direct').
 * @param {number} [input.flowLengthFt] Longest flow path L, ft (mode 'kirpich').
 * @param {number} [input.slopePct]     Mean flow-path slope, % (mode 'kirpich').
 * @returns {{isValid: true, peakFlowCfs: number, tcMin: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function rationalMethod(input) {
  const errors = [];
  if (input.mode !== 'direct' && input.mode !== 'kirpich') {
    return failure([{ field: 'mode', message: 'Select a Tc entry mode.' }]);
  }
  const C = requireNumber(errors, 'runoffC', input.runoffC, 'Runoff coefficient', { min: 0.05, max: 1 });
  const A = requireNumber(errors, 'areaAcres', input.areaAcres, 'Drainage area', { max: 640 });
  const i = requireNumber(errors, 'intensityInHr', input.intensityInHr, 'Rainfall intensity', { max: 25 });

  let tcMin;
  if (input.mode === 'direct') {
    tcMin = requireNumber(errors, 'tcMin', input.tcMin, 'Time of concentration', { min: 1, max: 1440 });
  } else {
    const L = requireNumber(errors, 'flowLengthFt', input.flowLengthFt, 'Flow length', { min: 10 });
    const Spct = requireNumber(errors, 'slopePct', input.slopePct, 'Flow-path slope', { max: 100 });
    if (!errors.length) {
      tcMin = 0.0078 * Math.pow(L, 0.77) * Math.pow(Spct / 100, -0.385);
    }
  }
  if (errors.length) return failure(errors);

  const peakFlowCfs = C * i * A;

  const bad = guardResults({ peakFlowCfs, tcMin }, 'areaAcres');
  if (bad) return bad;

  return {
    isValid: true,
    peakFlowCfs,
    tcMin,
    flag: 'info',
    flagMessage: 'Feed value — use this Q as the design flow for the pipe-sizing, detention, and outlet calculators below. Read i from the local IDF curve at this Tc; intensity is regional and is not built in.'
  };
}

/* =========================================================================
   2 · Storm drain pipe sizing (Manning's, full circular flow)
   ========================================================================= */

/** Standard storm drain sizes carried by this suite, inches. */
const STANDARD_SIZES_IN = [12, 15, 18, 24, 30, 36, 42, 48, 54, 60];

/**
 * Full-flow Manning capacity of a circular pipe.
 * Q = (1.49/n)·A·R^(2/3)·S^(1/2) with A = πD²/4, R = D/4
 *   → Q = 0.4644/n · D^(8/3) · √S   (D in ft)
 *
 * @param {number} dFt @param {number} n @param {number} S
 * @returns {number} cfs
 */
function manningFullFlow(dFt, n, S) {
  return 0.4644 / n * Math.pow(dFt, 8 / 3) * Math.sqrt(S);
}

/**
 * Minimum circular pipe diameter by Manning's equation (full flow), rounded
 * up to the nearest standard storm drain size, with a partial-flow depth
 * estimate for the selected size.
 *
 * Equations:
 *   Q = (1.49/n) · A · R^(2/3) · S^(1/2),  R = D/4 (full circular)
 *   D_req (ft) = [ Q·n / (0.4644·√S) ]^(3/8)
 *
 * Partial-flow depth d/D is found by bisection on the wetted angle θ:
 *   A = D²/8·(θ − sin θ),  R = D/4·(1 − sin θ/θ)
 *
 * Reference: Manning's equation per FHWA HEC-22 Ch. 5 / standard practice.
 *
 * @param {Object} input
 * @param {number} input.designFlowCfs Design flow Q, cfs (> 0).
 * @param {number} input.slopeFtFt     Pipe slope S, ft/ft (> 0).
 * @param {string|number} input.manningN Manning roughness n (from the material list).
 * @returns {{isValid: true, minDiameterIn: number, standardSizeIn?: number, capacityCfs?: number, utilizationPct?: number, flowDepthRatioPct?: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function pipeSizing(input) {
  const errors = [];
  const Q = requireNumber(errors, 'designFlowCfs', input.designFlowCfs, 'Design flow');
  const S = requireNumber(errors, 'slopeFtFt', input.slopeFtFt, 'Pipe slope', { max: 1 });
  const n = requireNumber(errors, 'manningN', Number(input.manningN), "Manning's n", { min: 0.008, max: 0.05 });
  if (errors.length) return failure(errors);

  const minDiameterFt = Math.pow(Q * n / (0.4644 * Math.sqrt(S)), 3 / 8);
  const minDiameterIn = minDiameterFt * 12;

  const standardSizeIn = STANDARD_SIZES_IN.find((size) => size >= minDiameterIn);
  if (!standardSizeIn) {
    const bad = guardResults({ minDiameterIn }, 'designFlowCfs');
    if (bad) return bad;
    return {
      isValid: true,
      minDiameterIn,
      flag: 'exceeds',
      flagMessage: 'Required diameter exceeds 60 in — beyond this suite\'s standard size list. Consider parallel barrels, a box section, or a flatter alignment, and a full design analysis.'
    };
  }

  const dFt = standardSizeIn / 12;
  const capacityCfs = manningFullFlow(dFt, n, S);
  const utilizationPct = 100 * Q / capacityCfs;

  // Partial-flow depth at design Q in the selected size. Manning discharge
  // rises monotonically with θ up to ~5.28 rad (d/D ≈ 0.94, the Q maximum),
  // so bisection on that interval finds the first (design) crossing.
  const partialFlow = (theta) =>
    (1.49 / n) * circArea(theta, dFt) * Math.pow(circHydraulicRadius(theta, dFt), 2 / 3) * Math.sqrt(S);
  let flowDepthRatioPct;
  const thetaMax = 5.28;
  if (Q >= partialFlow(thetaMax)) {
    flowDepthRatioPct = 100;
  } else {
    let lo = 1e-3, hi = thetaMax;
    for (let k = 0; k < 60; k++) {
      const mid = (lo + hi) / 2;
      if (partialFlow(mid) < Q) lo = mid; else hi = mid;
    }
    flowDepthRatioPct = 100 * circDepth((lo + hi) / 2, dFt) / dFt;
  }

  const bad = guardResults(
    { minDiameterIn, capacityCfs, utilizationPct, flowDepthRatioPct },
    'designFlowCfs'
  );
  if (bad) return bad;

  return {
    isValid: true,
    minDiameterIn,
    standardSizeIn,
    capacityCfs,
    utilizationPct,
    flowDepthRatioPct,
    flag: 'ok',
    flagMessage: 'Rounded up to the nearest standard size. Check minimum velocity (self-cleansing, typ. ≥ 2–3 fps) and the governing agency\'s minimum size and cover.'
  };
}

/* =========================================================================
   3 · Inlet capacity — sump / sag condition only
   ========================================================================= */

/**
 * Interception capacity of a grate or curb-opening inlet in a sump (sag),
 * per the simplified HEC-22 Ch. 4 sag equations. On-grade interception
 * efficiency is materially more complex and is NOT modeled here.
 *
 * Equations (sag condition):
 *   Grate, weir:    Q = Cw · P · d^1.5      (Cw ≈ 3.0; P = effective perimeter)
 *   Grate, orifice: Q = Co · A · √(2g·d)    (Co ≈ 0.67; controls at d ≳ 0.4 ft)
 *   Curb opening, weir: Q = Cw · L · d^1.5  (Cw ≈ 3.0–3.6)
 * Grate capacity is taken as the lesser of weir and orifice (conservative
 * through the transition). Capacities are unclogged — apply the local
 * clogging factor. Reference: FHWA HEC-22, Chapter 4 (sag locations).
 *
 * @param {Object} input
 * @param {'grate'|'curb'} input.mode   Inlet type.
 * @param {number} input.pondingDepthFt Ponding depth d at the inlet, ft (> 0).
 * @param {number} [input.perimeterFt]  Grate effective perimeter P, ft (curb side excluded).
 * @param {number} [input.openAreaFt2]  Grate clear opening area A, ft².
 * @param {number} [input.grateWeirCw]  Grate weir coefficient (≈ 3.0).
 * @param {number} [input.grateOrificeCo] Grate orifice coefficient (≈ 0.67).
 * @param {number} [input.openingLengthFt] Curb opening length L, ft.
 * @param {number} [input.curbWeirCw]   Curb weir coefficient (3.0–3.6).
 * @returns {{isValid: true, interceptionCfs: number, weirCfs: number, orificeCfs?: number, controlling: string, flag: string, flagMessage: string}|CalcFailure}
 */
export function inletCapacity(input) {
  const errors = [];
  if (input.mode !== 'grate' && input.mode !== 'curb') {
    return failure([{ field: 'mode', message: 'Select an inlet type.' }]);
  }
  const d = requireNumber(errors, 'pondingDepthFt', input.pondingDepthFt, 'Ponding depth', { max: 10 });

  if (input.mode === 'curb') {
    const L = requireNumber(errors, 'openingLengthFt', input.openingLengthFt, 'Opening length', { max: 100 });
    const Cw = requireNumber(errors, 'curbWeirCw', input.curbWeirCw, 'Weir coefficient', { min: 2, max: 4 });
    if (errors.length) return failure(errors);

    const weirCfs = Cw * L * Math.pow(d, 1.5);
    const bad = guardResults({ weirCfs }, 'openingLengthFt');
    if (bad) return bad;

    return {
      isValid: true,
      interceptionCfs: weirCfs,
      weirCfs,
      controlling: 'WEIR',
      flag: 'info',
      flagMessage: 'Sump weir capacity, unclogged. Above roughly 1.4 × the opening height the curb opening transitions to orifice flow — not modeled here. Apply the local clogging factor.'
    };
  }

  const P = requireNumber(errors, 'perimeterFt', input.perimeterFt, 'Effective perimeter', { max: 100 });
  const Ao = requireNumber(errors, 'openAreaFt2', input.openAreaFt2, 'Clear opening area', { max: 100 });
  const Cw = requireNumber(errors, 'grateWeirCw', input.grateWeirCw, 'Weir coefficient', { min: 2, max: 4 });
  const Co = requireNumber(errors, 'grateOrificeCo', input.grateOrificeCo, 'Orifice coefficient', { min: 0.4, max: 1 });
  if (errors.length) return failure(errors);

  const weirCfs = Cw * P * Math.pow(d, 1.5);
  const orificeCfs = Co * Ao * Math.sqrt(2 * GRAVITY * d);
  const weirControls = weirCfs <= orificeCfs;
  const interceptionCfs = weirControls ? weirCfs : orificeCfs;

  const bad = guardResults({ weirCfs, orificeCfs, interceptionCfs }, 'pondingDepthFt');
  if (bad) return bad;

  return {
    isValid: true,
    interceptionCfs,
    weirCfs,
    orificeCfs,
    controlling: weirControls ? 'WEIR' : 'ORIFICE',
    flag: 'info',
    flagMessage: (weirControls
      ? 'Weir flow controls at this depth (lesser of the two regimes governs).'
      : 'Orifice flow controls at this depth (lesser of the two regimes governs).')
      + ' Capacity is unclogged — HEC-22 suggests ~50% clogging on sag grates; confirm the local factor.'
  };
}

/* =========================================================================
   4 · Detention basin sizing — Modified Rational, triangular hydrograph
   ========================================================================= */

/**
 * Preliminary detention storage by the Modified Rational Method with a
 * triangular inflow/outflow approximation, checked across several trial
 * storm durations to approximate the critical duration.
 *
 * Equation (per trial duration):
 *   Vs (cf) = (Qin − Qout) · Td · 60 / 2
 * The governing (largest) Vs is reported. Qin must correspond to the IDF
 * intensity at each trial duration — a single Qin may be broadcast across
 * durations for a quick bound, but a true critical-duration search re-runs
 * calculator 1 per duration.
 *
 * Small-site preliminary method only — not a substitute for full hydrograph
 * routing (TR-55/TR-20 or continuous simulation) on larger or complex
 * sites. Reference: Modified Rational Method per common drainage-manual
 * practice (derived from FHWA HEC-22 Rational Method basis).
 *
 * @param {Object} input
 * @param {string} input.qinListCfs      Peak inflow(s) Qin, cfs — one value, or one per duration.
 * @param {string} input.durationsMinList Trial storm duration(s) Td, min, comma-separated.
 * @param {number} input.qoutCfs         Allowable release rate Qout, cfs (≥ 0).
 * @returns {{isValid: true, storageCf: number, storageAcFt: number, governingTdMin: number, governingQinCfs: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function detentionBasin(input) {
  const errors = [];
  const qins = requireNumberList(errors, 'qinListCfs', input.qinListCfs, 'Peak inflow', { max: 10000 });
  const durations = requireNumberList(errors, 'durationsMinList', input.durationsMinList, 'Storm duration', { min: 1, max: 1440 });
  const Qout = requireNumber(errors, 'qoutCfs', input.qoutCfs, 'Release rate', { allowZero: true });
  if (errors.length || !qins || !durations) return failure(errors);

  if (qins.length !== 1 && qins.length !== durations.length) {
    return failure([{ field: 'qinListCfs', message: 'Enter one Qin, or exactly one Qin per duration (' + durations.length + ' needed).' }]);
  }

  let storageCf = 0;
  let governingTdMin = durations[0];
  let governingQinCfs = qins[0];
  durations.forEach((Td, j) => {
    const Qin = qins.length === 1 ? qins[0] : qins[j];
    const Vs = Math.max(0, (Qin - Qout) * Td * 60 / 2);
    if (Vs > storageCf) {
      storageCf = Vs;
      governingTdMin = Td;
      governingQinCfs = Qin;
    }
  });
  const storageAcFt = storageCf / SQFT_PER_ACRE;

  const bad = guardResults({ storageCf, storageAcFt, governingTdMin, governingQinCfs }, 'qinListCfs');
  if (bad) return bad;

  if (storageCf === 0) {
    return {
      isValid: true,
      storageCf,
      storageAcFt,
      governingTdMin,
      governingQinCfs,
      flag: 'info',
      flagMessage: 'The allowable release meets or exceeds every trial inflow — this method computes no required storage. Confirm Qout against the downstream constraint.'
    };
  }

  return {
    isValid: true,
    storageCf,
    storageAcFt,
    governingTdMin,
    governingQinCfs,
    flag: 'ok',
    flagMessage: 'Largest Vs across ' + durations.length + ' trial duration(s). Check durations bracketing the critical storm (Qin from the IDF intensity at each Td). Preliminary small-site method — full hydrograph routing governs final design.'
  };
}

/* =========================================================================
   5 · Detention outlet structure — orifice + weir sizing
   ========================================================================= */

/**
 * Size a low-flow orifice or an overflow weir for a target release rate.
 *
 * Equations:
 *   Orifice: Q = Cd · A · √(2g·h)   → A = Q / (Cd·√(2g·h)),  Cd ≈ 0.6
 *   Weir (sharp-crested rectangular): Q = Cw · L · H^1.5 → L = Q / (Cw·H^1.5),
 *   Cw ≈ 3.0–3.33
 *
 * h is measured to the orifice centroid; H is the head above the weir
 * crest. Reference: standard orifice/weir equations per FHWA HEC-22 and
 * hydraulics texts.
 *
 * @param {Object} input
 * @param {'orifice'|'weir'} input.mode  Element to size.
 * @param {number} input.releaseQCfs     Target release rate Q, cfs (> 0).
 * @param {number} [input.orificeHeadFt] Head on the orifice centroid h, ft.
 * @param {number} [input.orificeCd]     Discharge coefficient Cd (≈ 0.6).
 * @param {number} [input.weirHeadFt]    Head above the weir crest H, ft.
 * @param {number} [input.weirCw]        Weir coefficient Cw (3.0–3.33).
 * @returns {{isValid: true, orificeDiameterIn?: number, orificeAreaFt2?: number, weirLengthFt?: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function outletStructure(input) {
  const errors = [];
  if (input.mode !== 'orifice' && input.mode !== 'weir') {
    return failure([{ field: 'mode', message: 'Select an outlet element.' }]);
  }
  const Q = requireNumber(errors, 'releaseQCfs', input.releaseQCfs, 'Release rate', { max: 10000 });

  if (input.mode === 'orifice') {
    const h = requireNumber(errors, 'orificeHeadFt', input.orificeHeadFt, 'Head on orifice', { max: 100 });
    const Cd = requireNumber(errors, 'orificeCd', input.orificeCd, 'Discharge coefficient', { min: 0.3, max: 1 });
    if (errors.length) return failure(errors);

    const orificeAreaFt2 = Q / (Cd * Math.sqrt(2 * GRAVITY * h));
    const orificeDiameterIn = 12 * Math.sqrt(4 * orificeAreaFt2 / Math.PI);

    const bad = guardResults({ orificeAreaFt2, orificeDiameterIn }, 'releaseQCfs');
    if (bad) return bad;

    const small = orificeDiameterIn < 3;
    return {
      isValid: true,
      orificeAreaFt2,
      orificeDiameterIn,
      flag: small ? 'review' : 'ok',
      flagMessage: small
        ? 'Computed orifice is under 3 in — small orifices clog. Many agencies set a minimum orifice size and require a trash rack; check the governing standard.'
        : 'Head h is to the orifice centroid at the design water surface. Provide a trash rack and confirm the minimum orifice size with the governing agency.'
    };
  }

  const H = requireNumber(errors, 'weirHeadFt', input.weirHeadFt, 'Head above crest', { max: 20 });
  const Cw = requireNumber(errors, 'weirCw', input.weirCw, 'Weir coefficient', { min: 2.5, max: 4 });
  if (errors.length) return failure(errors);

  const weirLengthFt = Q / (Cw * Math.pow(H, 1.5));

  const bad = guardResults({ weirLengthFt }, 'releaseQCfs');
  if (bad) return bad;

  return {
    isValid: true,
    weirLengthFt,
    flag: 'ok',
    flagMessage: 'Sharp-crested rectangular weir, free (unsubmerged) discharge, end contractions ignored. Size the emergency spillway for the check storm per the governing standard.'
  };
}

/* =========================================================================
   6 · Culvert capacity screening — inlet vs. outlet control
   ========================================================================= */

/**
 * HDS-5 inlet-control constants for circular culverts, by material and
 * entrance type. K/M fit the unsubmerged (form 1) equation; c/Y fit the
 * submerged equation; ke is the outlet-control entrance loss coefficient;
 * n is a typical barrel Manning roughness. slopeCoef is the slope-term
 * multiplier (−0.5 standard; +0.7 for mitered inlets per HDS-5).
 *
 * REVIEWER FLAG — verify every constant against FHWA HDS-5 Appendix A
 * (inlet-control coefficients) and Table C.2 (entrance loss) before publishing.
 */
const CULVERT_CONFIGS = {
  'conc-square-hw':   { n: 0.012, ke: 0.5, K: 0.0098, M: 2.0,  c: 0.0398, Y: 0.67, slopeCoef: -0.5 },
  'conc-groove-hw':   { n: 0.012, ke: 0.2, K: 0.0018, M: 2.0,  c: 0.0292, Y: 0.74, slopeCoef: -0.5 },
  'conc-groove-proj': { n: 0.012, ke: 0.2, K: 0.0045, M: 2.0,  c: 0.0317, Y: 0.69, slopeCoef: -0.5 },
  'cmp-headwall':     { n: 0.024, ke: 0.5, K: 0.0078, M: 2.0,  c: 0.0379, Y: 0.69, slopeCoef: -0.5 },
  'cmp-mitered':      { n: 0.024, ke: 0.7, K: 0.0210, M: 1.33, c: 0.0463, Y: 0.75, slopeCoef: 0.7 },
  'cmp-projecting':   { n: 0.024, ke: 0.9, K: 0.0340, M: 1.5,  c: 0.0553, Y: 0.54, slopeCoef: -0.5 }
};

/**
 * Simplified FHWA HDS-5 headwater screening for a circular culvert:
 * inlet control (nomograph-fit equations) vs. outlet control (full-flow
 * energy balance), reporting the controlling condition.
 *
 * Inlet control (HW/D, with F = Q/(A·D^0.5)):
 *   Unsubmerged (form 1, F ≤ 3.5): HW/D = Hc/D + K·F^M + cs·S
 *   Submerged   (F ≥ 4.0):         HW/D = c·F² + Y + cs·S
 *   (linear interpolation between; cs = −0.5, or +0.7 mitered)
 *   Hc = dc + Vc²/2g at critical depth in the circular barrel.
 *
 * Outlet control (full-flow approximation):
 *   H  = [1 + ke + 29·n²·L / R^(4/3)] · V²/2g,   R = D/4, V = Q/A
 *   HWo = ho + H − S·L,   ho = max(TW, (dc + D)/2)
 *
 * Screening only — partial-flow outlet control, inlet depression, skew,
 * and non-circular shapes need the full HDS-5 procedure (or HY-8).
 *
 * @param {Object} input
 * @param {number} input.designQCfs   Design discharge Q, cfs (> 0).
 * @param {number} input.diameterIn   Barrel diameter, in (≥ 12).
 * @param {string} input.config       Material/entrance key (CULVERT_CONFIGS).
 * @param {number} input.lengthFt     Barrel length L, ft (> 0).
 * @param {number} input.slopeFtFt    Barrel slope S, ft/ft (> 0).
 * @param {number} input.tailwaterFt  Tailwater depth above outlet invert TW, ft (≥ 0).
 * @param {number} input.allowableHwFt Allowable headwater, ft (> 0).
 * @returns {{isValid: true, inletHwFt: number, outletHwFt: number, controllingHwFt: number, controlling: string, flag: string, flagMessage: string}|CalcFailure}
 */
export function culvertScreening(input) {
  const errors = [];
  const cfg = CULVERT_CONFIGS[input.config];
  if (!cfg) {
    return failure([{ field: 'config', message: 'Select a culvert material and entrance type.' }]);
  }
  const Q = requireNumber(errors, 'designQCfs', input.designQCfs, 'Design discharge');
  const Din = requireNumber(errors, 'diameterIn', input.diameterIn, 'Barrel diameter', { min: 12, max: 144 });
  const L = requireNumber(errors, 'lengthFt', input.lengthFt, 'Barrel length', { min: 1, max: 2000 });
  const S = requireNumber(errors, 'slopeFtFt', input.slopeFtFt, 'Barrel slope', { max: 0.5 });
  const TW = requireNumber(errors, 'tailwaterFt', input.tailwaterFt, 'Tailwater depth', { allowZero: true, max: 100 });
  const HWallow = requireNumber(errors, 'allowableHwFt', input.allowableHwFt, 'Allowable headwater', { max: 100 });
  if (errors.length) return failure(errors);

  const D = Din / 12;
  const A = Math.PI * D * D / 4;
  const F = Q / (A * Math.sqrt(D));
  const { dcFt, acFt2 } = circularCriticalDepth(Q, D);

  /* --- Inlet control --- */
  const Hc = dcFt + Math.pow(Q / acFt2, 2) / (2 * GRAVITY);
  const hwUnsub = Hc / D + cfg.K * Math.pow(F, cfg.M) + cfg.slopeCoef * S;
  const hwSub = cfg.c * F * F + cfg.Y + cfg.slopeCoef * S;
  let hwOverD;
  if (F <= 3.5) hwOverD = hwUnsub;
  else if (F >= 4.0) hwOverD = hwSub;
  else hwOverD = hwUnsub + (hwSub - hwUnsub) * (F - 3.5) / 0.5;
  const inletHwFt = hwOverD * D;

  /* --- Outlet control (full-flow) --- */
  const R = D / 4;
  const V = Q / A;
  const H = (1 + cfg.ke + 29 * cfg.n * cfg.n * L / Math.pow(R, 4 / 3)) * V * V / (2 * GRAVITY);
  const ho = Math.max(TW, (dcFt + D) / 2);
  const outletHwFt = ho + H - S * L;

  const inletControls = inletHwFt >= outletHwFt;
  const controllingHwFt = inletControls ? inletHwFt : outletHwFt;

  const bad = guardResults({ inletHwFt, outletHwFt, controllingHwFt }, 'designQCfs');
  if (bad) return bad;

  const over = controllingHwFt > HWallow;
  const highRatio = controllingHwFt / D > 3;
  let flag, flagMessage;
  if (over) {
    flag = 'exceeds';
    flagMessage = 'Controlling headwater exceeds the allowable — upsize the barrel, improve the entrance, or revisit the alignment.';
  } else if (highRatio) {
    flag = 'review';
    flagMessage = 'HW/D exceeds ~3 — beyond the nomograph-fit range of the inlet-control equations. Run the full HDS-5 procedure (or HY-8).';
  } else {
    flag = 'ok';
    flagMessage = 'Within the allowable headwater. Screening result — confirm with the full HDS-5 procedure (or HY-8) for final design.';
  }

  return {
    isValid: true,
    inletHwFt,
    outletHwFt,
    controllingHwFt,
    controlling: inletControls ? 'INLET CONTROL' : 'OUTLET CONTROL',
    flag,
    flagMessage
  };
}

/* =========================================================================
   7 · Outlet protection — riprap apron sizing (simplified HEC-14)
   ========================================================================= */

/**
 * Riprap apron median stone size and apron dimensions for a minor circular
 * outlet, per the simplified FHWA HEC-14 apron method.
 *
 * Equations (D in ft; discharge intensity Fd = Q / (√g · D^2.5)):
 *   d50 (ft) = 0.2 · D · Fd^(4/3) · (D / TW)
 *   La (ft)  = D · (8 + 17 · log10 Fd),  floored at 4·D
 *   W  (ft)  = 3·D + (2/3)·La            (no defined downstream channel)
 * Tailwater condition sets TW: minimal/unknown → 0.4·D; adequate → D.
 *
 * Simplified method for minor outlets — high discharge intensity, drop
 * outlets, or complex tailwater require a full HEC-14 energy-dissipator
 * design. Reference: FHWA HEC-14 (3rd ed.), riprap apron design.
 * REVIEWER FLAG — verify relations and the TW assumptions against HEC-14
 * before publishing.
 *
 * @param {Object} input
 * @param {number} input.diameterIn Outlet pipe diameter, in (≥ 12).
 * @param {number} input.designQCfs Design discharge Q, cfs (> 0).
 * @param {'minimal'|'adequate'} input.tailwater Tailwater condition.
 * @returns {{isValid: true, d50In: number, apronLengthFt: number, apronWidthFt: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function riprapApron(input) {
  const errors = [];
  if (input.tailwater !== 'minimal' && input.tailwater !== 'adequate') {
    return failure([{ field: 'tailwater', message: 'Select a tailwater condition.' }]);
  }
  const Din = requireNumber(errors, 'diameterIn', input.diameterIn, 'Pipe diameter', { min: 12, max: 120 });
  const Q = requireNumber(errors, 'designQCfs', input.designQCfs, 'Design discharge');
  if (errors.length) return failure(errors);

  const D = Din / 12;
  const Fd = Q / (Math.sqrt(GRAVITY) * Math.pow(D, 2.5));
  const TW = (input.tailwater === 'minimal' ? 0.4 : 1.0) * D;

  const d50Ft = 0.2 * D * Math.pow(Fd, 4 / 3) * (D / TW);
  const d50In = d50Ft * 12;
  const apronLengthFt = Math.max(4 * D, D * (8 + 17 * Math.log10(Fd)));
  const apronWidthFt = 3 * D + (2 / 3) * apronLengthFt;

  const bad = guardResults({ d50In, apronLengthFt, apronWidthFt }, 'designQCfs');
  if (bad) return bad;

  const intense = Fd > 2.5;
  return {
    isValid: true,
    d50In,
    apronLengthFt,
    apronWidthFt,
    flag: intense ? 'review' : 'ok',
    flagMessage: intense
      ? 'Discharge intensity is beyond the simplified apron range — an engineered energy dissipator (full HEC-14 design) is likely required.'
      : 'Simplified minimum-protection method for minor outlets. Round d50 up to the nearest local riprap class; apron thickness typ. 2×d50 over filter fabric.'
  };
}
