/* =========================================================================
   North Bay Digital Foundry — Civil Transportation Engineering Suite
   Pure deterministic engineering functions. No DOM or storage access.

   Canonical internal units are SI except the AASHTO 1993 pavement equation,
   whose resilient-modulus input is explicitly psi. Inputs and outputs are
   documented per function. Results retain full precision; display rounding
   belongs to the controller.
   ========================================================================= */

import { LOS_THRESHOLDS } from './transportation-reference-data.js';

const G = 9.80665;
const MPH_TO_MPS = 0.44704;
const KMH_TO_MPS = 1 / 3.6;
const FT_TO_M = 0.3048;

function failure(errors) { return { isValid: false, errors }; }

function number(errors, field, value, label, options = {}) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    errors.push({ field, message: `${label} must be a finite number.` });
    return NaN;
  }
  if (options.min !== undefined && value < options.min) {
    errors.push({ field, message: `${label} must be at least ${options.min}.` });
  }
  if (options.max !== undefined && value > options.max) {
    errors.push({ field, message: `${label} must be no more than ${options.max}.` });
  }
  if (options.positive && value <= 0) {
    errors.push({ field, message: `${label} must be greater than zero.` });
  }
  return value;
}

function requiredText(errors, field, value, label) {
  if (typeof value !== 'string' || value.trim() === '') {
    errors.push({ field, message: `${label} is required.` });
    return '';
  }
  if (value.length > 160) errors.push({ field, message: `${label} is too long.` });
  return value.trim();
}

function unitSystem(errors, value) {
  if (value !== 'us' && value !== 'si') {
    errors.push({ field: 'unitSystem', message: 'Select US customary or SI units.' });
  }
  return value;
}

function speedMps(value, units) {
  return value * (units === 'us' ? MPH_TO_MPS : KMH_TO_MPS);
}

function lengthFromM(value, units) {
  return units === 'us' ? value / FT_TO_M : value;
}

function lengthToM(value, units) {
  return units === 'us' ? value * FT_TO_M : value;
}

function finiteResult(values, field = 'result') {
  return Object.values(values).every((v) => typeof v !== 'number' || Number.isFinite(v))
    ? null
    : failure([{ field, message: 'The calculation produced a non-finite result.' }]);
}

/**
 * Stopping sight distance. Speed is mph (US) or km/h (SI); deceleration is
 * ft/s² (US) or m/s² (SI); output distances use ft or m.
 * Positive grade is upgrade and increases effective deceleration.
 */
export function stoppingSightDistance(input) {
  const errors = [];
  const units = unitSystem(errors, input.unitSystem);
  const speed = number(errors, 'speed', input.speed, 'Design speed', { positive: true, max: units === 'us' ? 150 : 240 });
  const reactionTime = number(errors, 'reactionTime', input.reactionTime, 'Perception-reaction time', { positive: true, max: 10 });
  const gradePct = number(errors, 'gradePct', input.gradePct, 'Grade', { min: -25, max: 25 });
  if (!['deceleration', 'friction'].includes(input.method)) {
    errors.push({ field: 'method', message: 'Select a calculation method.' });
  }
  let baseDecelMps2;
  if (input.method === 'deceleration') {
    const a = number(errors, 'deceleration', input.deceleration, 'Deceleration rate', { positive: true, max: units === 'us' ? 40 : 12 });
    baseDecelMps2 = units === 'us' ? a * FT_TO_M : a;
  } else {
    const f = number(errors, 'friction', input.friction, 'Longitudinal friction factor', { positive: true, max: 1 });
    baseDecelMps2 = G * f;
  }
  if (errors.length) return failure(errors);

  const v = speedMps(speed, units);
  const gradeDecimal = gradePct / 100;
  const effectiveDecelMps2 = baseDecelMps2 + G * gradeDecimal;
  if (effectiveDecelMps2 <= 0) {
    return failure([{ field: input.method === 'deceleration' ? 'deceleration' : 'friction', message: 'Grade makes the effective braking denominator zero or negative.' }]);
  }
  const reactionDistanceM = v * reactionTime;
  const brakingDistanceM = v * v / (2 * effectiveDecelMps2);
  const totalDistanceM = reactionDistanceM + brakingDistanceM;
  const result = {
    isValid: true,
    unitSystem: units,
    speedMps: v,
    gradeDecimal,
    baseDecelMps2,
    effectiveDecelMps2,
    reactionDistance: lengthFromM(reactionDistanceM, units),
    brakingDistance: lengthFromM(brakingDistanceM, units),
    totalDistance: lengthFromM(totalDistanceM, units),
    roundedDesignDistance: Math.ceil(lengthFromM(totalDistanceM, units)),
    method: input.method,
    warning: Math.abs(gradePct) > 10 ? 'Grade exceeds the suite’s typical screening range; verify the governing method.' : ''
  };
  return finiteResult(result) || result;
}

/**
 * Horizontal curve point-mass relation v²/(gR)=e+f.
 * Speed is mph or km/h; radius is ft or m; e is entered in percent.
 */
export function horizontalCurve(input) {
  const errors = [];
  const units = unitSystem(errors, input.unitSystem);
  const speed = number(errors, 'speed', input.speed, 'Design speed', { positive: true, max: units === 'us' ? 150 : 240 });
  const ePct = number(errors, 'superelevationPct', input.superelevationPct, 'Superelevation criterion', { min: -12, max: 16 });
  const f = number(errors, 'friction', input.friction, 'Side-friction factor', { min: 0, max: 0.5 });
  if (!['radius', 'superelevation', 'friction'].includes(input.solveMode)) {
    errors.push({ field: 'solveMode', message: 'Select a solve mode.' });
  }
  let radius;
  if (input.solveMode !== 'radius') {
    radius = number(errors, 'radius', input.radius, 'Curve radius', { positive: true });
  }
  if (errors.length) return failure(errors);

  const v = speedMps(speed, units);
  const e = ePct / 100;
  let radiusM;
  let demand;
  let requiredSuperelevationPct = null;
  let requiredFriction = null;
  if (input.solveMode === 'radius') {
    if (e + f <= 0) return failure([{ field: 'superelevationPct', message: 'Superelevation plus friction must be greater than zero.' }]);
    radiusM = v * v / (G * (e + f));
    demand = e + f;
  } else {
    radiusM = lengthToM(radius, units);
    demand = v * v / (G * radiusM);
    if (input.solveMode === 'superelevation') requiredSuperelevationPct = (demand - f) * 100;
    if (input.solveMode === 'friction') requiredFriction = demand - e;
  }
  const criterionExceeded = input.solveMode === 'superelevation'
    ? requiredSuperelevationPct > ePct
    : input.solveMode === 'friction'
      ? requiredFriction > f
      : false;
  const result = {
    isValid: true,
    unitSystem: units,
    solveMode: input.solveMode,
    speedMps: v,
    superelevationDecimal: e,
    combinedDemand: demand,
    radius: lengthFromM(radiusM, units),
    requiredSuperelevationPct,
    requiredFriction,
    criterionExceeded,
    warning: demand > 0.35 ? 'Combined lateral demand is high for a planning screen; verify agency criteria and curve design.' : ''
  };
  return finiteResult(result) || result;
}

/**
 * Vertical curve K-value method. Grades are percent; K and output length use
 * ft/% (US) or m/% (SI). K is always user supplied in this implementation.
 */
export function verticalCurve(input) {
  const errors = [];
  const units = unitSystem(errors, input.unitSystem);
  if (!['crest', 'sag'].includes(input.curveType)) errors.push({ field: 'curveType', message: 'Select crest or sag.' });
  const g1 = number(errors, 'g1Pct', input.g1Pct, 'Entering grade', { min: -25, max: 25 });
  const g2 = number(errors, 'g2Pct', input.g2Pct, 'Exiting grade', { min: -25, max: 25 });
  const k = number(errors, 'kValue', input.kValue, 'K-value', { positive: true });
  const minimum = number(errors, 'minimumLength', input.minimumLength, 'Minimum curve length', { min: 0 });
  if (errors.length) return failure(errors);
  const gradeDifferencePct = Math.abs(g2 - g1);
  if (gradeDifferencePct === 0) return failure([{ field: 'g2Pct', message: 'The algebraic grade difference must be greater than zero.' }]);
  const calculatedLength = k * gradeDifferencePct;
  return {
    isValid: true,
    unitSystem: units,
    curveType: input.curveType,
    gradeDifferencePct,
    selectedK: k,
    calculatedLength,
    minimumLength: minimum,
    finalLength: Math.max(calculatedLength, minimum),
    controllingCriterion: minimum > calculatedLength ? 'User-entered minimum length' : 'K-value calculation',
    kSource: 'User-entered design criterion',
    warning: gradeDifferencePct > 20 ? 'Algebraic grade difference exceeds the typical screening range; verify geometric feasibility.' : ''
  };
}

// Peter J. Acklam's rational approximation of the inverse standard-normal
// CDF. The pavement workflow uses the lower-tail quantile 1 - R so the
// AASHTO reliability deviate is negative above 50% reliability.
function standardNormalQuantile(probability) {
  const a = [-3.969683028665376e+1, 2.209460984245205e+2, -2.759285104469687e+2,
    1.38357751867269e+2, -3.066479806614716e+1, 2.506628277459239];
  const b = [-5.447609879822406e+1, 1.615858368580409e+2, -1.556989798598866e+2,
    6.680131188771972e+1, -1.328068155288572e+1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
    -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
    3.754408661907416];
  const lower = 0.02425;
  const upper = 1 - lower;

  if (probability < lower) {
    const q = Math.sqrt(-2 * Math.log(probability));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (probability > upper) {
    const q = Math.sqrt(-2 * Math.log(1 - probability));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  const q = probability - 0.5;
  const r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

function pavementRightSide(sn, input) {
  const deltaPsi = input.initialServiceability - input.terminalServiceability;
  const reliabilityTerm = input.zR * input.standardDeviation;
  const structuralTerm = 9.36 * Math.log10(sn + 1) - 0.20;
  const serviceabilityNumerator = Math.log10(deltaPsi / (4.2 - 1.5));
  const serviceabilityDenominator = 0.40 + 1094 / Math.pow(sn + 1, 5.19);
  const serviceabilityTerm = serviceabilityNumerator / serviceabilityDenominator;
  const subgradeTerm = 2.32 * Math.log10(input.resilientModulusPsi) - 8.07;
  return { reliabilityTerm, structuralTerm, serviceabilityNumerator, serviceabilityDenominator, serviceabilityTerm, subgradeTerm,
    rhs: reliabilityTerm + structuralTerm + serviceabilityTerm + subgradeTerm };
}

/**
 * Solve the AASHTO 1993 flexible-pavement equation by bisection.
 * W18 is ESALs, MR is psi, and SN is dimensionless. ZR is derived from the
 * entered reliability as the corresponding lower-tail standard-normal value.
 */
export function pavementStructuralNumber(input) {
  const errors = [];
  const w18 = number(errors, 'w18', input.w18, 'Design ESALs', { positive: true });
  const reliabilityPct = number(errors, 'reliabilityPct', input.reliabilityPct, 'Reliability', { min: 50, max: 99.999 });
  const so = number(errors, 'standardDeviation', input.standardDeviation, 'Overall standard deviation', { positive: true, max: 1.5 });
  const pi = number(errors, 'initialServiceability', input.initialServiceability, 'Initial serviceability', { positive: true, max: 5 });
  const pt = number(errors, 'terminalServiceability', input.terminalServiceability, 'Terminal serviceability', { positive: true, max: 5 });
  const mr = number(errors, 'resilientModulusPsi', input.resilientModulusPsi, 'Resilient modulus', { positive: true });
  const tolerance = number(errors, 'tolerance', input.tolerance, 'Numerical tolerance', { positive: true, max: 0.01 });
  const snMax = number(errors, 'snMax', input.snMax ?? 20, 'Maximum SN search bound', { positive: true, max: 100 });
  if (pi <= pt) errors.push({ field: 'terminalServiceability', message: 'Initial serviceability must be greater than terminal serviceability.' });
  if (errors.length) return failure(errors);

  const zR = standardNormalQuantile(1 - reliabilityPct / 100);
  const target = Math.log10(w18);
  const args = { ...input, w18, standardDeviation: so, initialServiceability: pi, terminalServiceability: pt, resilientModulusPsi: mr, zR };
  const residualAt = (sn) => pavementRightSide(sn, args).rhs - target;
  let lo = 0;
  let hi = snMax;
  let flo = residualAt(lo);
  let fhi = residualAt(hi);
  if (!Number.isFinite(flo) || !Number.isFinite(fhi) || flo * fhi > 0) {
    return failure([{ field: 'snMax', message: 'The selected SN interval [0, ' + snMax + '] does not bracket a solution.' }]);
  }
  let mid = 0;
  let residual = flo;
  let iterations = 0;
  for (; iterations < 200; iterations += 1) {
    mid = (lo + hi) / 2;
    residual = residualAt(mid);
    if (Math.abs(residual) <= tolerance || (hi - lo) / 2 <= tolerance) break;
    if (flo * residual <= 0) {
      hi = mid;
      fhi = residual;
    } else {
      lo = mid;
      flo = residual;
    }
  }
  const terms = pavementRightSide(mid, args);
  return {
    isValid: true,
    reliabilityPct,
    deltaPsi: pi - pt,
    zR,
    zRSource: 'Derived from the entered reliability using the standard-normal quantile',
    structuralNumber: mid,
    iterations: iterations + 1,
    residual,
    converged: Math.abs(residual) <= tolerance || (hi - lo) / 2 <= tolerance,
    targetLogW18: target,
    ...terms,
    warning: 'Structural number does not define layer thicknesses, coefficients, drainage factors, or minimum sections.'
  };
}

/**
 * Directional intersection planning screen. Each approach must provide
 * {name, demand, capacity, delay}. Demand is either a 60-minute hourly volume
 * or a peak 15-minute count; capacity is veh/h and delay is user-entered
 * seconds/vehicle. No delay model is implied.
 */
export function intersectionScreening(input) {
  const errors = [];
  if (!['signalized', 'twsc', 'awsc'].includes(input.controlType)) {
    errors.push({ field: 'controlType', message: 'Select a supported control type.' });
  }
  const periodMinutes = number(errors, 'periodMinutes', input.periodMinutes, 'Analysis period', { positive: true, max: 60 });
  const phf = number(errors, 'peakHourFactor', input.peakHourFactor, 'Peak-hour factor', { positive: true, max: 1 });
  if (Number.isFinite(periodMinutes) && ![15, 60].includes(periodMinutes)) {
    errors.push({ field: 'periodMinutes', message: 'Analysis period must be either 15 or 60 minutes.' });
  }
  const alertRatio = number(errors, 'alertRatio', input.alertRatio, 'Approaching-capacity threshold', { min: 0.5, max: 1 });
  if (!Array.isArray(input.approaches) || input.approaches.length < 1 || input.approaches.length > 8) {
    errors.push({ field: 'approaches', message: 'Provide 1–8 directional approaches.' });
  }
  const approaches = Array.isArray(input.approaches) ? input.approaches.map((a, i) => {
    const prefix = `approach${i}`;
    const demand = number(errors, `${prefix}Demand`, a.demand, `${a.name || 'Approach'} demand`, { min: 0 });
    const capacity = number(errors, `${prefix}Capacity`, a.capacity, `${a.name || 'Approach'} capacity`, { positive: true });
    const delay = number(errors, `${prefix}Delay`, a.delay, `${a.name || 'Approach'} control delay`, { min: 0, max: 1000 });
    const lanes = requiredText(errors, `${prefix}Lanes`, a.lanes, `${a.name || 'Approach'} lane configuration`);
    return { name: String(a.name || `Approach ${i + 1}`), demand, capacity, delay, lanes };
  }) : [];
  if (errors.length) return failure(errors);
  const thresholds = LOS_THRESHOLDS[input.controlType];
  const letters = ['A', 'B', 'C', 'D', 'E', 'F'];
  const classified = approaches.map((a) => {
    // HCM PHF = hourly volume / (4 × peak 15-minute count). A peak
    // 15-minute count already defines the peak flow rate when multiplied by
    // four; dividing that result by PHF would count the same peaking twice.
    const peakFlowRate = periodMinutes === 15 ? a.demand * 4 : a.demand / phf;
    const hourlyVolume = periodMinutes === 15 ? peakFlowRate * phf : a.demand;
    const volumeCapacityRatio = peakFlowRate / a.capacity;
    const losIndex = thresholds.findIndex((limit) => a.delay <= limit);
    return {
      ...a,
      hourlyVolume,
      peakFlowRate,
      hourlyDemand: peakFlowRate,
      volumeCapacityRatio,
      los: letters[losIndex === -1 ? 5 : losIndex],
      capacityFlag: volumeCapacityRatio > 1 ? 'Demand exceeds assumed capacity' :
        volumeCapacityRatio >= alertRatio ? 'Approaching assumed capacity' : 'Below assumed capacity'
    };
  });
  const controlling = classified.reduce((worst, a) => a.volumeCapacityRatio > worst.volumeCapacityRatio ? a : worst);
  return {
    isValid: true,
    controlType: input.controlType,
    periodMinutes,
    peakHourFactor: phf,
    demandBasis: periodMinutes === 15 ? 'Peak 15-minute count' : '60-minute hourly volume',
    approaches: classified,
    controllingApproach: controlling.name,
    controllingRatio: controlling.volumeCapacityRatio,
    controllingLos: controlling.los,
    thresholdSource: 'FHWA/HCM-aligned control-delay thresholds',
    warning: 'This is a directional capacity screen using user-entered delay and capacity, not a formal intersection-wide HCM analysis.'
  };
}

/**
 * Stop-controlled departure sight triangle. Speed is mph or km/h; geometry
 * outputs use ft or m. Time gap is a user-supplied design criterion.
 */
export function sightTriangle(input) {
  const errors = [];
  const units = unitSystem(errors, input.unitSystem);
  const speed = number(errors, 'speed', input.speed, 'Major-road design speed', { positive: true, max: units === 'us' ? 150 : 240 });
  const majorGrade = number(errors, 'majorGradePct', input.majorGradePct, 'Major-road grade', { min: -20, max: 20 });
  const minorGrade = number(errors, 'minorGradePct', input.minorGradePct, 'Minor-road grade', { min: -20, max: 20 });
  const lanes = number(errors, 'lanes', input.lanes, 'Crossed or entered lanes', { min: 1, max: 12 });
  const laneWidth = number(errors, 'laneWidth', input.laneWidth, 'Lane width', { positive: true });
  const medianWidth = number(errors, 'medianWidth', input.medianWidth, 'Median width', { min: 0 });
  const setback = number(errors, 'setback', input.setback, 'Driver-eye setback', { positive: true });
  const timeGap = number(errors, 'timeGap', input.timeGap, 'Time gap', { positive: true, max: 30 });
  const vehicle = requiredText(errors, 'vehicle', input.vehicle, 'Design vehicle / criterion note');
  if (errors.length) return failure(errors);
  const speedMetersPerSecond = speedMps(speed, units);
  const majorLegM = speedMetersPerSecond * timeGap;
  const crossingWidth = lanes * laneWidth + medianWidth;
  return {
    isValid: true,
    unitSystem: units,
    speedMps: speedMetersPerSecond,
    minorLeg: setback,
    majorLeg: lengthFromM(majorLegM, units),
    crossingWidth,
    baseTimeGap: timeGap,
    adjustedTimeGap: timeGap,
    vehicle,
    timeGapSource: 'User-supplied design criterion; no automatic lane or grade adjustment',
    warning: (majorGrade !== 0 || minorGrade !== 0) ? 'Grades are recorded but not automatically adjusted; verify the governing case-specific criteria.' : ''
  };
}

/**
 * Manual average-rate trip generation. Rate units must match quantity units.
 * User-entered reductions are applied internal capture, pass-by, then
 * diverted-link and are reported separately.
 */
export function tripGeneration(input) {
  const errors = [];
  const quantity = number(errors, 'quantity', input.quantity, 'Independent-variable quantity', { positive: true });
  const landUse = requiredText(errors, 'landUse', input.landUse, 'Land-use category');
  const source = requiredText(errors, 'source', input.source, 'Data source');
  const edition = requiredText(errors, 'edition', input.edition, 'Source edition / date');
  if (!['dwelling-units', 'ksf', 'employees', 'custom'].includes(input.variableType)) errors.push({ field: 'variableType', message: 'Select an independent-variable type.' });
  if (input.method !== 'average-rate') errors.push({ field: 'method', message: 'Select the supported average-rate method.' });

  const rate = number(errors, 'rate', input.rate, 'Trip rate', { min: 0 });
  const enteringPct = number(errors, 'enteringPct', input.enteringPct, 'Entering percentage', { min: 0, max: 100 });
  const exitingPct = number(errors, 'exitingPct', input.exitingPct, 'Exiting percentage', { min: 0, max: 100 });
  const passByPct = number(errors, 'passByPct', input.passByPct, 'Pass-by adjustment', { min: 0, max: 100 });
  const divertedPct = number(errors, 'divertedPct', input.divertedPct, 'Diverted-link adjustment', { min: 0, max: 100 });
  const internalPct = number(errors, 'internalPct', input.internalPct, 'Internal-capture adjustment', { min: 0, max: 100 });
  if (!['am', 'pm'].includes(input.period)) errors.push({ field: 'period', message: 'Select AM or PM peak hour.' });
  if (Math.abs(enteringPct + exitingPct - 100) > 1e-9) {
    errors.push({ field: 'exitingPct', message: 'Entering and exiting percentages must total 100%.' });
  }
  if (errors.length) return failure(errors);
  const rawTrips = rate * quantity;
  const afterInternalCapture = rawTrips * (1 - internalPct / 100);
  const afterPassBy = afterInternalCapture * (1 - passByPct / 100);
  const afterDiverted = afterPassBy * (1 - divertedPct / 100);
  const drivewayTrips = afterInternalCapture;
  const newExternalRoadwayTrips = afterDiverted;
  return {
    isValid: true,
    landUse,
    source,
    edition,
    period: input.period,
    quantity,
    rate,
    rawTrips,
    drivewayTrips,
    drivewayEnteringTrips: drivewayTrips * enteringPct / 100,
    drivewayExitingTrips: drivewayTrips * exitingPct / 100,
    newExternalRoadwayTrips,
    newExternalEnteringTrips: newExternalRoadwayTrips * enteringPct / 100,
    newExternalExitingTrips: newExternalRoadwayTrips * exitingPct / 100,
    enteringTrips: newExternalRoadwayTrips * enteringPct / 100,
    exitingTrips: newExternalRoadwayTrips * exitingPct / 100,
    internalCaptureReduction: rawTrips - afterInternalCapture,
    passByReduction: afterInternalCapture - afterPassBy,
    divertedReduction: afterPassBy - afterDiverted,
    adjustedTrips: newExternalRoadwayTrips,
    warning: 'No proprietary ITE data are bundled. Validate the supplied rate, local context, and adjustment policy.'
  };
}
