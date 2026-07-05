/* =========================================================================
   North Bay Digital Foundry — Potable Pipeline Engineering Suite
   Pure engineering calculation layer (ES module).

   Rules for this module:
   • No DOM access, no localStorage, no event listeners.
   • Every exported function accepts a plain object of numbers (US customary
     units, documented per function) and returns an explicit result object:
       success → { isValid: true,  ...results }
       failure → { isValid: false, errors: [{ field, message }] }
   • Preliminary-design methods only. Every result must be independently
     verified by a licensed professional engineer.
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
const GAMMA_WATER = 62.4;    // unit weight of fresh water, lb/ft³
const GRAVITY = 32.174;      // gravitational acceleration, ft/s²
const PSI_PER_FT = 0.4333;   // pressure of one foot of water column, psi/ft
const GAMMA_CONCRETE = 150;  // normal-weight concrete, lb/ft³ (ballast sizing)

/* --- Runtime guards ------------------------------------------------------ */
const MAX_MAGNITUDE = 1e6;   // overflow guard on inputs and results
const MIN_MAGNITUDE = 1e-3;  // underflow guard on non-zero inputs

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
 * @param {FieldError[]} errors
 * @returns {CalcFailure}
 */
function failure(errors) {
  return { isValid: false, errors };
}

/**
 * Guard computed results against overflow / non-finite values.
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

/** @param {number} deg @returns {number} radians */
function toRadians(deg) {
  return deg * Math.PI / 180;
}

/* =========================================================================
   1 · Hazen-Williams head loss
   ========================================================================= */

/**
 * Hazen-Williams friction head loss for a full-flowing circular water pipe.
 *
 * Equation (US customary form):
 *   hf (ft) = 10.44 · L · Q^1.852 / (C^1.852 · d^4.8655)
 *   ΔP (psi) = 0.4333 · hf
 *
 * Valid for turbulent flow of potable water near 60 °F. C is empirical
 * (material- and age-dependent). Reference: Williams & Hazen; AWWA M32.
 *
 * @param {Object} input
 * @param {number} input.flowGpm    Flow rate, gpm (> 0).
 * @param {number} input.diameterIn Pipe inside diameter, in (≥ 1).
 * @param {number} input.cFactor    Hazen-Williams C factor (30–160).
 * @param {number} input.lengthFt   Pipeline length, ft (> 0).
 * @returns {{isValid: true, headLossFt: number, pressureDropPsi: number}|CalcFailure}
 */
export function hazenWilliams(input) {
  const errors = [];
  const Q = requireNumber(errors, 'flowGpm', input.flowGpm, 'Flow rate');
  const d = requireNumber(errors, 'diameterIn', input.diameterIn, 'Pipe diameter', { min: 1 });
  const C = requireNumber(errors, 'cFactor', input.cFactor, 'C factor', { min: 30, max: 160 });
  const L = requireNumber(errors, 'lengthFt', input.lengthFt, 'Pipeline length');
  if (errors.length) return failure(errors);

  const headLossFt = 10.44 * L * Math.pow(Q, 1.852) /
    (Math.pow(C, 1.852) * Math.pow(d, 4.8655));
  const pressureDropPsi = PSI_PER_FT * headLossFt;

  const bad = guardResults({ headLossFt, pressureDropPsi }, 'flowGpm');
  if (bad) return bad;

  return { isValid: true, headLossFt, pressureDropPsi };
}

/* =========================================================================
   2 · Velocity constraint check
   ========================================================================= */

/**
 * Mean pipe velocity from continuity, with a municipal design-range flag.
 *
 * Equation (exact identity, not empirical):
 *   V (fps) = 0.4085 · Q (gpm) / d² (in)
 *
 * Flag tiers (industry approximation — verify against the governing agency):
 *   < 2 fps   informational (turnover / sedimentation check)
 *   2–5 fps   typical municipal design range
 *   5–8 fps   upper municipal limit range — review
 *   > 8 fps   exceeds typical municipal maximum
 * The computed velocity is never clamped.
 *
 * @param {Object} input
 * @param {number} input.flowGpm    Flow rate, gpm (> 0).
 * @param {number} input.diameterIn Pipe inside diameter, in (≥ 1).
 * @returns {{isValid: true, velocityFps: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function velocityCheck(input) {
  const errors = [];
  const Q = requireNumber(errors, 'flowGpm', input.flowGpm, 'Flow rate');
  const d = requireNumber(errors, 'diameterIn', input.diameterIn, 'Pipe diameter', { min: 1 });
  if (errors.length) return failure(errors);

  const velocityFps = 0.4085 * Q / (d * d);

  const bad = guardResults({ velocityFps }, 'flowGpm');
  if (bad) return bad;

  let flag, flagMessage;
  if (velocityFps < 2) {
    flag = 'info';
    flagMessage = 'Below 2 fps — informational. Check turnover, water age, and sedimentation.';
  } else if (velocityFps <= 5) {
    flag = 'ok';
    flagMessage = 'Within the typical municipal design range (2–5 fps).';
  } else if (velocityFps <= 8) {
    flag = 'review';
    flagMessage = 'In the upper municipal limit range (5–8 fps) — review against the governing standard.';
  } else {
    flag = 'exceeds';
    flagMessage = 'Exceeds the typical municipal maximum (8 fps).';
  }

  return { isValid: true, velocityFps, flag, flagMessage };
}

/* =========================================================================
   3 · Joukowsky surge (instantaneous closure)
   ========================================================================= */

/**
 * Joukowsky surge pressure for an instantaneous velocity change.
 *
 * Equations:
 *   ΔP (psi) = ρ · a · ΔV / 144        (ρ in slug/ft³, a and ΔV in fps)
 *   ΔH (ft)  = a · ΔV / g              (g = 32.174 ft/s²)
 *   Total transient = operating pressure + ΔP
 *
 * Upper-bound single-event estimate: assumes full flow stoppage in less than
 * one wave round-trip (t < 2L/a); ignores friction, reflections, and column
 * separation. Reference: Joukowsky (1898); AWWA M11.
 *
 * @param {Object} input
 * @param {number} input.velocityFps          Initial velocity ΔV, fps (> 0).
 * @param {number} input.waveSpeedFps         Pressure wave speed a, fps (> 0).
 * @param {number} input.fluidDensitySlugFt3  Fluid mass density, slug/ft³ (water ≈ 1.94).
 * @param {number} input.operatingPressurePsi Steady operating pressure, psi (≥ 0).
 * @returns {{isValid: true, surgePsi: number, surgeHeadFt: number, totalPsi: number}|CalcFailure}
 */
export function joukowskySurge(input) {
  const errors = [];
  const dV = requireNumber(errors, 'velocityFps', input.velocityFps, 'Initial velocity');
  const a = requireNumber(errors, 'waveSpeedFps', input.waveSpeedFps, 'Wave speed');
  const rho = requireNumber(errors, 'fluidDensitySlugFt3', input.fluidDensitySlugFt3, 'Fluid density');
  const Po = requireNumber(errors, 'operatingPressurePsi', input.operatingPressurePsi, 'Operating pressure', { allowZero: true });
  if (errors.length) return failure(errors);

  const surgePsi = rho * a * dV / 144;
  const surgeHeadFt = a * dV / GRAVITY;
  const totalPsi = Po + surgePsi;

  const bad = guardResults({ surgePsi, surgeHeadFt, totalPsi }, 'waveSpeedFps');
  if (bad) return bad;

  return { isValid: true, surgePsi, surgeHeadFt, totalPsi };
}

/* =========================================================================
   4 · Barlow hoop stress (wall thickness ⇄ allowable pressure)
   ========================================================================= */

/**
 * Barlow thin-wall hoop-stress formula, solved for wall thickness or for
 * maximum allowable pressure.
 *
 * Equations (thin-wall, outside diameter):
 *   t (in)  = P · Do / (2 · S)
 *   P (psi) = 2 · S · t / Do
 *
 * S is the allowable hoop stress and must already include the design/safety
 * factor. Reference: Barlow's formula per AWWA M11 practice; the AWWA
 * C900/C905 pressure-class equation PC = 2·HDS/(DR−1) is the same relation
 * expressed in dimension-ratio form.
 *
 * @param {Object} input
 * @param {'thickness'|'pressure'} input.mode  Which quantity to solve for.
 * @param {number} input.outsideDiameterIn     Outside diameter Do, in (≥ 1).
 * @param {number} input.allowableStressPsi    Allowable hoop stress S, psi (> 0).
 * @param {number} [input.pressurePsi]         Internal pressure P, psi (mode 'thickness').
 * @param {number} [input.wallThicknessIn]     Wall thickness t, in (mode 'pressure').
 * @returns {{isValid: true, wallThicknessIn?: number, maxPressurePsi?: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function barlow(input) {
  const errors = [];
  if (input.mode !== 'thickness' && input.mode !== 'pressure') {
    return failure([{ field: 'mode', message: 'Select what to solve for.' }]);
  }
  const Do = requireNumber(errors, 'outsideDiameterIn', input.outsideDiameterIn, 'Outside diameter', { min: 1 });

  if (input.mode === 'thickness') {
    const P = requireNumber(errors, 'pressurePsi', input.pressurePsi, 'Internal pressure');
    const S = requireNumber(errors, 'allowableStressPsi', input.allowableStressPsi, 'Allowable hoop stress');
    if (errors.length) return failure(errors);

    const wallThicknessIn = P * Do / (2 * S);
    const bad = guardResults({ wallThicknessIn }, 'pressurePsi');
    if (bad) return bad;

    const marginal = wallThicknessIn / Do > 0.10;
    return {
      isValid: true,
      wallThicknessIn,
      flag: marginal ? 'review' : 'ok',
      flagMessage: marginal
        ? 'Thin-wall assumption is marginal (t/Do > 0.10). Barlow is conservative here; consider a thick-wall check.'
        : 'Thin-wall assumption satisfied (t/Do ≤ 0.10).'
    };
  }

  const t = requireNumber(errors, 'wallThicknessIn', input.wallThicknessIn, 'Wall thickness');
  const S = requireNumber(errors, 'allowableStressPsi', input.allowableStressPsi, 'Allowable hoop stress');
  if (errors.length) return failure(errors);
  if (t >= Do / 2) {
    return failure([{ field: 'wallThicknessIn', message: 'Wall thickness must be less than half the outside diameter.' }]);
  }

  const maxPressurePsi = 2 * S * t / Do;
  const bad = guardResults({ maxPressurePsi }, 'wallThicknessIn');
  if (bad) return bad;

  const marginal = t / Do > 0.10;
  return {
    isValid: true,
    maxPressurePsi,
    flag: marginal ? 'review' : 'ok',
    flagMessage: marginal
      ? 'Thin-wall assumption is marginal (t/Do > 0.10). Barlow is conservative here; consider a thick-wall check.'
      : 'Thin-wall assumption satisfied (t/Do ≤ 0.10).'
  };
}

/* =========================================================================
   5 · Restrained length at a horizontal bend (friction-only)
   ========================================================================= */

/**
 * DIPRA-aligned preliminary restrained length each side of a horizontal bend,
 * using longitudinal friction resistance only (no passive soil bearing).
 *
 * Equations:
 *   A  (in²)   = π · Do² / 4                      (thrust area on the OD)
 *   T  (lb)    = 2 · P · A · sin(θ/2)             (resultant thrust, reported)
 *   We (lb/ft) = γs · Hc · Do / 12                (soil prism above the pipe)
 *   Fs (lb/ft) = f · (2 · We + Wp+w)              (unit friction resistance)
 *   L  (ft)    = SF · P · A · tan(θ/2) / Fs       (each side of the bend)
 *
 * Friction-only simplification is conservative relative to the full DIPRA
 * method. Reference framework: DIPRA, "Thrust Restraint Design for Ductile
 * Iron Pipe"; AWWA M41.
 *
 * @param {Object} input
 * @param {number} input.outsideDiameterIn    Pipe outside diameter Do, in (≥ 1).
 * @param {number} input.pressurePsi          Design/test pressure P, psi (> 0).
 * @param {number} input.bendAngleDeg         Fitting deflection angle θ, deg (0 < θ ≤ 90).
 * @param {number} input.frictionCoeff        Soil-to-pipe friction coefficient f (0 < f ≤ 1).
 * @param {number} input.pipeWaterWeightLbFt  Pipe + contained water weight, lb/ft (> 0).
 * @param {number} input.soilUnitWeightLbFt3  Soil unit weight γs, lb/ft³ (> 0).
 * @param {number} input.coverDepthFt         Depth of cover Hc, ft (> 0).
 * @param {number} input.safetyFactor         Safety factor SF (≥ 1; DIPRA practice 1.5).
 * @returns {{isValid: true, thrustLb: number, unitFrictionLbFt: number, restrainedLengthFt: number}|CalcFailure}
 */
export function restrainedLength(input) {
  const errors = [];
  const Do = requireNumber(errors, 'outsideDiameterIn', input.outsideDiameterIn, 'Outside diameter', { min: 1 });
  const P = requireNumber(errors, 'pressurePsi', input.pressurePsi, 'Design pressure');
  const theta = requireNumber(errors, 'bendAngleDeg', input.bendAngleDeg, 'Fitting angle', { max: 90 });
  const f = requireNumber(errors, 'frictionCoeff', input.frictionCoeff, 'Friction coefficient', { max: 1 });
  const Wpw = requireNumber(errors, 'pipeWaterWeightLbFt', input.pipeWaterWeightLbFt, 'Pipe + water weight');
  const gammaS = requireNumber(errors, 'soilUnitWeightLbFt3', input.soilUnitWeightLbFt3, 'Soil unit weight');
  const Hc = requireNumber(errors, 'coverDepthFt', input.coverDepthFt, 'Cover depth');
  const SF = requireNumber(errors, 'safetyFactor', input.safetyFactor, 'Safety factor', { min: 1, max: 10 });
  if (errors.length) return failure(errors);

  const area = Math.PI * Do * Do / 4;                    // in²
  const half = toRadians(theta) / 2;
  const thrustLb = 2 * P * area * Math.sin(half);
  const earthPrismLbFt = gammaS * Hc * (Do / 12);
  const unitFrictionLbFt = f * (2 * earthPrismLbFt + Wpw);

  if (unitFrictionLbFt <= 0) {
    return failure([{ field: 'frictionCoeff', message: 'Unit friction resistance computes to zero — check friction and weight inputs.' }]);
  }

  const restrainedLengthFt = SF * P * area * Math.tan(half) / unitFrictionLbFt;

  const bad = guardResults({ thrustLb, unitFrictionLbFt, restrainedLengthFt }, 'pressurePsi');
  if (bad) return bad;

  return { isValid: true, thrustLb, unitFrictionLbFt, restrainedLengthFt };
}

/* =========================================================================
   6 · Modified Iowa deflection (flexible pipe, external loading)
   ========================================================================= */

/**
 * Modified Iowa (Spangler/Watkins) predicted vertical ring deflection for
 * buried flexible pipe, in the AWWA M23/M45 pipe-stiffness form.
 *
 * Equations:
 *   Wc (psi) = γs · H / 144                          (prism earth load)
 *   Δy/D (%) = 100 · (DL·Wc + WL) · K / (0.149·PS + 0.061·E′)
 *
 * PS is pipe stiffness per ASTM D2412; E′ is the modulus of soil reaction
 * (Howard/USBR values). With prism load, DL = 1.0 is standard practice.
 * Reference: Spangler (1941) as modified by Watkins (1958); AWWA M23/M45/M55.
 *
 * @param {Object} input
 * @param {number} input.pipeStiffnessPsi     Pipe stiffness PS, psi (> 0, ASTM D2412).
 * @param {number} input.soilModulusPsi       Modulus of soil reaction E′, psi (> 0).
 * @param {number} input.beddingConstant      Bedding constant K (0.08–0.11 typical).
 * @param {number} input.deflectionLag        Deflection lag factor DL (1.0–1.5).
 * @param {number} input.soilUnitWeightLbFt3  Soil unit weight γs, lb/ft³ (> 0).
 * @param {number} input.coverDepthFt         Depth of cover H, ft (> 0).
 * @param {number} input.liveLoadPsi          Live load WL at pipe depth, psi (≥ 0).
 * @returns {{isValid: true, earthLoadPsi: number, deflectionPct: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function modifiedIowa(input) {
  const errors = [];
  const PS = requireNumber(errors, 'pipeStiffnessPsi', input.pipeStiffnessPsi, 'Pipe stiffness');
  const E = requireNumber(errors, 'soilModulusPsi', input.soilModulusPsi, 'Soil modulus E′');
  const K = requireNumber(errors, 'beddingConstant', input.beddingConstant, 'Bedding constant', { min: 0.05, max: 0.15 });
  const DL = requireNumber(errors, 'deflectionLag', input.deflectionLag, 'Deflection lag factor', { min: 1, max: 2.5 });
  const gammaS = requireNumber(errors, 'soilUnitWeightLbFt3', input.soilUnitWeightLbFt3, 'Soil unit weight');
  const H = requireNumber(errors, 'coverDepthFt', input.coverDepthFt, 'Cover depth');
  const WL = requireNumber(errors, 'liveLoadPsi', input.liveLoadPsi, 'Live load', { allowZero: true });
  if (errors.length) return failure(errors);

  const earthLoadPsi = gammaS * H / 144;
  const denominator = 0.149 * PS + 0.061 * E;
  if (denominator <= 0) {
    return failure([{ field: 'pipeStiffnessPsi', message: 'Stiffness terms compute to zero — check PS and E′.' }]);
  }

  const deflectionPct = 100 * (DL * earthLoadPsi + WL) * K / denominator;

  const bad = guardResults({ earthLoadPsi, deflectionPct }, 'coverDepthFt');
  if (bad) return bad;

  const over = deflectionPct > 5;
  return {
    isValid: true,
    earthLoadPsi,
    deflectionPct,
    flag: over ? 'review' : 'ok',
    flagMessage: over
      ? 'Exceeds the 5% initial-deflection limit commonly applied to PVC (AWWA M23) — review pipe stiffness, embedment, or cover.'
      : 'Within the 5% initial-deflection limit commonly applied to PVC (AWWA M23). Allowable deflection varies by material.'
  };
}

/* =========================================================================
   7 · Buoyancy / flotation
   ========================================================================= */

/**
 * Flotation safety factor for a buried pipe, fully-submerged worst case
 * (pipe empty, groundwater at or above the pipe), with concrete ballast
 * sizing when the safety factor is not met.
 *
 * Equations (per foot of pipe):
 *   Fb = γw · π · (Do/12)² / 4                          (uplift, empty pipe)
 *   Wp = γp · π/4 · [(Do/12)² − ((Do−2t)/12)²]          (pipe wall weight)
 *   Ws = [γs·(Hc−Hsub) + (γs−γw)·Hsub] · Do/12          (soil prism; buoyant
 *        below the water table)  where Hsub = min(Hw, Hc)
 *   SF = (Wp + Ws) / Fb
 *   Ballast (net, submerged) = SFreq·Fb − (Wp + Ws)
 *   Ballast (concrete, air weight) = net · γc / (γc − γw),  γc = 150 lb/ft³
 *
 * Industry approximation (Archimedes + prism method, per AWWA M11 flotation
 * discussion and ASCE buried-pipe practice) — verify with a PE; required SF
 * varies by agency (1.1–1.5 typical).
 *
 * @param {Object} input
 * @param {number} input.outsideDiameterIn   Outside diameter Do, in (≥ 1).
 * @param {number} input.wallThicknessIn     Wall thickness t, in (> 0, < Do/2).
 * @param {number} input.pipeUnitWeightLbFt3 Pipe material unit weight γp, lb/ft³ (> 0).
 * @param {number} input.soilUnitWeightLbFt3 Soil unit weight γs, lb/ft³ (> 0; > 62.4 where submerged).
 * @param {number} input.coverDepthFt        Depth of cover Hc, ft (> 0).
 * @param {number} input.groundwaterDepthFt  Groundwater height above pipe crown Hw, ft (≥ 0).
 * @param {number} input.requiredSF          Required flotation safety factor (≥ 1).
 * @returns {{isValid: true, upliftLbFt: number, resistanceLbFt: number, safetyFactor: number, ballastConcreteLbFt: number, flag: string, flagMessage: string}|CalcFailure}
 */
export function buoyancy(input) {
  const errors = [];
  const Do = requireNumber(errors, 'outsideDiameterIn', input.outsideDiameterIn, 'Outside diameter', { min: 1 });
  const t = requireNumber(errors, 'wallThicknessIn', input.wallThicknessIn, 'Wall thickness');
  const gammaP = requireNumber(errors, 'pipeUnitWeightLbFt3', input.pipeUnitWeightLbFt3, 'Pipe unit weight');
  const gammaS = requireNumber(errors, 'soilUnitWeightLbFt3', input.soilUnitWeightLbFt3, 'Soil unit weight');
  const Hc = requireNumber(errors, 'coverDepthFt', input.coverDepthFt, 'Cover depth');
  const Hw = requireNumber(errors, 'groundwaterDepthFt', input.groundwaterDepthFt, 'Groundwater height', { allowZero: true });
  const SFreq = requireNumber(errors, 'requiredSF', input.requiredSF, 'Required safety factor', { min: 1, max: 10 });
  if (errors.length) return failure(errors);

  if (Number.isFinite(t) && Number.isFinite(Do) && t >= Do / 2) {
    return failure([{ field: 'wallThicknessIn', message: 'Wall thickness must be less than half the outside diameter.' }]);
  }

  const doFt = Do / 12;
  const diFt = (Do - 2 * t) / 12;
  const submergedFt = Math.min(Hw, Hc);
  if (submergedFt > 0 && gammaS <= GAMMA_WATER) {
    return failure([{ field: 'soilUnitWeightLbFt3', message: 'Submerged soil must weigh more than water (> 62.4 lb/ft³).' }]);
  }

  const upliftLbFt = GAMMA_WATER * Math.PI * doFt * doFt / 4;
  const pipeWeightLbFt = gammaP * Math.PI / 4 * (doFt * doFt - diFt * diFt);
  const soilWeightLbFt =
    (gammaS * (Hc - submergedFt) + (gammaS - GAMMA_WATER) * submergedFt) * doFt;
  const resistanceLbFt = pipeWeightLbFt + soilWeightLbFt;
  const safetyFactor = resistanceLbFt / upliftLbFt;

  let ballastConcreteLbFt = 0;
  const short = safetyFactor < SFreq;
  if (short) {
    const netLbFt = SFreq * upliftLbFt - resistanceLbFt;
    ballastConcreteLbFt = netLbFt * GAMMA_CONCRETE / (GAMMA_CONCRETE - GAMMA_WATER);
  }

  const bad = guardResults(
    { upliftLbFt, resistanceLbFt, safetyFactor, ballastConcreteLbFt },
    'outsideDiameterIn'
  );
  if (bad) return bad;

  return {
    isValid: true,
    upliftLbFt,
    resistanceLbFt,
    safetyFactor,
    ballastConcreteLbFt,
    flag: short ? 'exceeds' : 'ok',
    flagMessage: short
      ? 'Safety factor below the required value — concrete ballast (air weight shown) or added cover is needed.'
      : 'Safety factor meets the required value. No ballast needed for the fully-submerged, empty-pipe case.'
  };
}
