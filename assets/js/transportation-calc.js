/* Civil Transportation Engineering Suite — accessible UI/state controller.
   User-derived content is rendered only with textContent and DOM creation. */

import {
  stoppingSightDistance,
  horizontalCurve,
  verticalCurve,
  pavementStructuralNumber,
  intersectionScreening,
  sightTriangle,
  tripGeneration
} from './transportation-engineering.js';
import { TRANSPORTATION_REFERENCES } from './transportation-reference-data.js';

const STORAGE_KEY = 'nbdf_transportation_calc_v1';
const STORAGE_VERSION = 1;
const FORMS = Array.from(document.querySelectorAll('.transport-form[data-calc]'));

const f = (value, digits = 2) => Number(value).toLocaleString('en-US', {
  maximumFractionDigits: digits,
  minimumFractionDigits: 0
});

function lengthUnit(form) {
  return form.elements.unitSystem?.value === 'si' ? 'm' : 'ft';
}

function prepareFieldAccessibility(form) {
  form.querySelectorAll('input[name], select[name]').forEach((el) => {
    const field = el.closest('.transport-field');
    const label = field?.querySelector('.transport-label');
    if (!field || !label || !el.id) return;

    label.id ||= `${el.id}-label`;
    el.setAttribute('aria-labelledby', label.id);

    const help = field.querySelector('.transport-help');
    if (help) help.id ||= `${el.id}-help`;

    let error = field.querySelector('.transport-error');
    if (!error) {
      error = document.createElement('span');
      error.className = 'transport-error';
      error.hidden = true;
      field.append(error);
    }
    error.id ||= `${el.id}-error`;
    error.setAttribute('role', 'alert');
    el.setAttribute('aria-errormessage', error.id);
    el.setAttribute('aria-describedby', [help?.id, error.id].filter(Boolean).join(' '));
  });
}

function fieldError(form, name, message) {
  const el = form.elements[name];
  if (!el) return;
  const field = el.closest('.transport-field');
  const error = field?.querySelector('.transport-error');
  if (!error) return;
  error.textContent = message || '';
  error.hidden = !message;
  if (message) el.setAttribute('aria-invalid', 'true');
  else el.removeAttribute('aria-invalid');
}

function clearErrors(form) {
  form.querySelectorAll('[aria-invalid="true"]').forEach((el) => el.removeAttribute('aria-invalid'));
  form.querySelectorAll('.transport-error').forEach((el) => {
    el.textContent = '';
    el.hidden = true;
  });
}

function idle(form, message = 'Enter valid inputs and select Calculate. No result is shown until validation passes.') {
  const results = form.closest('.transport-workspace')?.querySelector('[data-results]');
  if (!results) return;
  results.replaceChildren();
  const p = document.createElement('p');
  p.className = 'transport-results__idle';
  p.textContent = message;
  results.append(p);
}

function values(form) {
  const out = {};
  Array.from(form.elements).forEach((el) => {
    if (!el.name || el.disabled || el.closest('[hidden]')) return;
    if (el.type === 'number') out[el.name] = el.value.trim() === '' ? NaN : Number(el.value);
    else out[el.name] = el.value;
  });
  return out;
}

function run(form, input) {
  switch (form.dataset.calc) {
    case 'ssd': return stoppingSightDistance(input);
    case 'horizontal': return horizontalCurve(input);
    case 'vertical': return verticalCurve(input);
    case 'pavement': return pavementStructuralNumber(input);
    case 'los':
      return intersectionScreening({
        controlType: input.controlType,
        periodMinutes: Number(input.periodMinutes),
        peakHourFactor: input.peakHourFactor,
        alertRatio: input.alertRatio,
        approaches: ['Northbound', 'Southbound', 'Eastbound', 'Westbound'].map((name, i) => ({
          name,
          demand: input[`approach${i}Demand`],
          capacity: input[`approach${i}Capacity`],
          delay: input[`approach${i}Delay`],
          lanes: input[`approach${i}Lanes`]
        }))
      });
    case 'sight': return sightTriangle(input);
    case 'trip': return tripGeneration(input);
    default: return { isValid: false, errors: [{ field: '', message: 'Unknown calculator.' }] };
  }
}

function resultModel(form, input, r) {
  const unit = lengthUnit(form);
  switch (form.dataset.calc) {
    case 'ssd':
      return {
        primary: `${f(r.totalDistance, 1)} ${unit} SSD`,
        interpretation: `The unrounded estimate combines ${f(r.reactionDistance, 1)} ${unit} of reaction travel and ${f(r.brakingDistance, 1)} ${unit} of braking travel.`,
        given: [`Speed: ${f(input.speed)} ${input.unitSystem === 'us' ? 'mph' : 'km/h'}`, `Reaction time: ${f(input.reactionTime)} s`, `Grade: ${f(input.gradePct)}% (upgrade positive)`, `Method: ${r.method}`],
        conversions: [`Speed used: ${f(r.speedMps, 3)} m/s`, `Grade used: ${f(r.gradeDecimal, 4)} decimal`, `Effective deceleration: ${f(r.effectiveDecelMps2, 3)} m/s²`],
        steps: [`Reaction distance = v × tr = ${f(r.reactionDistance, 2)} ${unit}`, `Braking distance = v² / (2aeffective) = ${f(r.brakingDistance, 2)} ${unit}`, `SSD = reaction + braking = ${f(r.totalDistance, 2)} ${unit}`, `Display design rounding (upward to 1 ${unit}) = ${f(r.roundedDesignDistance, 0)} ${unit}`]
      };
    case 'horizontal': {
      const solved = r.solveMode === 'radius' ? `${f(r.radius, 1)} ${unit} minimum radius`
        : r.solveMode === 'superelevation' ? `${f(r.requiredSuperelevationPct, 2)}% required superelevation`
          : `${f(r.requiredFriction, 3)} required side friction`;
      return {
        primary: solved,
        interpretation: r.criterionExceeded ? 'The calculated demand exceeds the user-entered maximum criterion.' : 'The calculated demand does not exceed the user-entered comparison criterion.',
        given: [`Speed: ${f(input.speed)} ${input.unitSystem === 'us' ? 'mph' : 'km/h'}`, `Superelevation criterion: ${f(input.superelevationPct)}%`, `Side-friction criterion: ${f(input.friction, 3)}`],
        conversions: [`Speed used: ${f(r.speedMps, 3)} m/s`, `Superelevation used: ${f(r.superelevationDecimal, 4)} decimal`],
        steps: [`Combined e + f demand = ${f(r.combinedDemand, 4)}`, `Point-mass substitution gives ${solved}`]
      };
    }
    case 'vertical':
      return {
        primary: `${f(r.finalLength, 1)} ${unit} preliminary length`,
        interpretation: `${r.controllingCriterion} controls for the ${r.curveType} curve.`,
        given: [`g₁: ${f(input.g1Pct)}%`, `g₂: ${f(input.g2Pct)}%`, `K: ${f(r.selectedK)} ${unit}/%`, `K source: ${r.kSource}`],
        conversions: ['Grades remain percentage values; A is calculated in percentage points.'],
        steps: [`A = |g₂ − g₁| = ${f(r.gradeDifferencePct)} percentage points`, `L = K × A = ${f(r.calculatedLength, 2)} ${unit}`, `Applied minimum = ${f(r.minimumLength, 2)} ${unit}`, `Controlling preliminary length = ${f(r.finalLength, 2)} ${unit}`]
      };
    case 'pavement':
      return {
        primary: `SN ${f(r.structuralNumber, 4)}`,
        interpretation: r.converged ? 'The bounded bisection solver converged within the selected tolerance.' : 'The solver did not converge.',
        given: [`W₁₈: ${f(input.w18, 0)} ESALs`, `Reliability: ${f(r.reliabilityPct)}%`, `MR: ${f(input.resilientModulusPsi, 0)} psi`],
        conversions: [`Reliability ${f(r.reliabilityPct)}% → ZR = ${f(r.zR, 4)} (standard-normal quantile)`, `ΔPSI = ${f(r.deltaPsi, 3)}`, `Target log₁₀(W₁₈) = ${f(r.targetLogW18, 6)}`],
        steps: [`ZR·Sₒ term = ${f(r.reliabilityTerm, 6)}`, `Structural term = ${f(r.structuralTerm, 6)}`, `Serviceability term = ${f(r.serviceabilityTerm, 6)}`, `Subgrade term = ${f(r.subgradeTerm, 6)}`, `Iterations = ${r.iterations}; residual = ${r.residual.toExponential(3)}`]
      };
    case 'los':
      return {
        primary: `${r.controllingApproach} controls at v/c ${f(r.controllingRatio, 2)}`,
        interpretation: `The controlling approach’s user-entered delay classifies as LOS ${r.controllingLos}. This is not intersection-wide formal HCM LOS.`,
        given: [`Control: ${input.controlType}`, `Demand basis: ${r.demandBasis}`, `PHF: ${f(r.peakHourFactor, 3)}`, `Capacity flag threshold: ${f(input.alertRatio, 2)} v/c`],
        conversions: [r.periodMinutes === 15
          ? 'Peak 15-minute counts are multiplied by four to obtain the HCM peak flow rate. PHF is not applied again.'
          : 'Hourly volumes are divided by PHF to obtain the HCM peak 15-minute-equivalent flow rate.'],
        steps: r.approaches.map((a) => r.periodMinutes === 15
          ? `${a.name}: ${f(a.demand, 0)} veh/15 min × 4 = ${f(a.peakFlowRate, 0)} veh/h peak flow rate; supplied PHF implies ${f(a.hourlyVolume, 0)} veh hourly volume; v/c ${f(a.volumeCapacityRatio, 2)}; ${f(a.delay, 1)} s/veh → LOS ${a.los}; ${a.capacityFlag}.`
          : `${a.name}: ${f(a.hourlyVolume, 0)} veh hourly volume ÷ PHF ${f(r.peakHourFactor, 3)} = ${f(a.peakFlowRate, 0)} veh/h peak flow rate; v/c ${f(a.volumeCapacityRatio, 2)}; ${f(a.delay, 1)} s/veh → LOS ${a.los}; ${a.capacityFlag}.`)
      };
    case 'sight':
      return {
        primary: `a = ${f(r.minorLeg, 1)} ${unit} · b = ${f(r.majorLeg, 1)} ${unit}`,
        interpretation: 'Leg a is the entered driver-eye setback to the near edge; leg b is measured along the major-road traveled way.',
        given: [`Major-road speed: ${f(input.speed)} ${input.unitSystem === 'us' ? 'mph' : 'km/h'}`, `Time gap: ${f(r.baseTimeGap)} s (user supplied)`, `Lanes: ${f(input.lanes, 0)}`, `Vehicle / criterion: ${input.vehicle}`],
        conversions: [`Speed used: ${f(r.speedMps, 3)} m/s`, `Crossing or entering width: ${f(r.crossingWidth, 2)} ${unit}`],
        steps: [`Base time gap = adjusted time gap = ${f(r.adjustedTimeGap)} s`, `b = speed × time gap = ${f(r.majorLeg, 2)} ${unit}`, `a = entered setback = ${f(r.minorLeg, 2)} ${unit}`]
      };
    case 'trip':
      return {
        primary: `${f(r.newExternalRoadwayTrips, 1)} new external roadway ${input.period.toUpperCase()} peak-hour trips`,
        interpretation: `Project driveways carry ${f(r.drivewayEnteringTrips, 1)} entering and ${f(r.drivewayExitingTrips, 1)} exiting trips, including pass-by and diverted-link traffic. Of those, ${f(r.newExternalEnteringTrips, 1)} entering and ${f(r.newExternalExitingTrips, 1)} exiting trips are new to the external roadway network.`,
        given: [`Land use: ${r.landUse}`, `Quantity: ${f(r.quantity)} ${input.variableType}`, `Rate: ${f(r.rate, 4)} trips/unit`, `Source: ${r.source}; edition/date: ${r.edition}`],
        conversions: ['Quantity is assumed already normalized to the supplied rate unit.'],
        steps: [`Raw site trip ends = R × X = ${f(r.rawTrips, 2)}`, `Internal-capture reduction = ${f(r.internalCaptureReduction, 2)}`, `External driveway trips after internal capture = ${f(r.drivewayTrips, 2)}`, `Pass-by reduction from new roadway traffic = ${f(r.passByReduction, 2)}`, `Diverted-link reduction from new roadway traffic = ${f(r.divertedReduction, 2)}`, `New external roadway trips = ${f(r.newExternalRoadwayTrips, 2)}`, `Directional split = ${f(input.enteringPct)}% entering / ${f(input.exitingPct)}% exiting`]
      };
    default: return null;
  }
}

function appendList(parent, title, items) {
  const group = document.createElement('div');
  group.className = 'result-group';
  const h = document.createElement('h4');
  h.textContent = title;
  const ul = document.createElement('ul');
  ul.className = 'result-list';
  items.forEach((item) => {
    const li = document.createElement('li');
    li.textContent = item;
    ul.append(li);
  });
  group.append(h, ul);
  parent.append(group);
}

function render(form, input, result) {
  const box = form.closest('.transport-workspace').querySelector('[data-results]');
  const model = resultModel(form, input, result);
  box.replaceChildren();
  const status = document.createElement('span');
  status.className = `result-status ${result.warning ? 'result-status--warning' : 'result-status--ok'}`;
  status.textContent = result.warning ? 'Calculated · review warning' : 'Calculated · valid inputs';
  const primary = document.createElement('p');
  primary.className = 'result-primary';
  primary.textContent = model.primary;
  const interpretation = document.createElement('p');
  interpretation.className = 'result-interpretation';
  interpretation.textContent = model.interpretation;
  box.append(status, primary, interpretation);
  if (result.warning) {
    const warning = document.createElement('p');
    warning.className = 'result-warning';
    warning.textContent = result.warning;
    box.append(warning);
  }
  appendList(box, 'Given inputs', model.given);
  appendList(box, 'Unit conversions', model.conversions);
  appendList(box, 'Calculation steps', model.steps);
  const refKey = ({ ssd: 'ssd', horizontal: 'horizontalCurve', vertical: 'verticalCurve', pavement: 'pavement', los: 'los', sight: 'sightTriangle', trip: 'tripGeneration' })[form.dataset.calc];
  const ref = TRANSPORTATION_REFERENCES[refKey];
  appendList(box, 'Calculation status', [`Method type: ${ref.kind}`, `Reference / edition: ${ref.source} ${ref.edition}`, 'Status: successful preliminary calculation; independent verification required.']);
}

function calculate(form) {
  clearErrors(form);
  const input = values(form);
  const result = run(form, input);
  if (!result.isValid) {
    result.errors.forEach((error) => fieldError(form, error.field, error.message));
    idle(form, `Calculation unavailable: ${result.errors[0]?.message || 'check the highlighted inputs.'}`);
    return;
  }
  render(form, input, result);
}

function save() {
  const valuesById = {};
  document.querySelectorAll('.transport-form input[id], .transport-form select[id]').forEach((el) => {
    if (el.value.length <= 160) valuesById[el.id] = el.value;
  });
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, values: valuesById })); } catch {}
}

function restore() {
  let parsed;
  try { parsed = JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch { return; }
  if (!parsed || parsed.version !== STORAGE_VERSION || typeof parsed.values !== 'object') return;
  Object.entries(parsed.values).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (!el || !el.closest('.transport-form') || typeof value !== 'string' || value.length > 160) return;
    if (el.tagName === 'SELECT') {
      if (Array.from(el.options).some((option) => option.value === value)) el.value = value;
    } else if (el.type === 'number') {
      if (value === '' || Number.isFinite(Number(value))) el.value = value;
    } else {
      el.value = value;
    }
  });
}

function convertUnits(form, previous, next) {
  if (!previous || previous === next) return;
  const toSi = previous === 'us' && next === 'si';
  form.querySelectorAll('[data-kind]').forEach((el) => {
    const value = Number(el.value);
    if (!Number.isFinite(value)) return;
    let factor = 1;
    if (el.dataset.kind === 'speed') factor = toSi ? 1.609344 : 1 / 1.609344;
    if (['length', 'k', 'deceleration'].includes(el.dataset.kind)) factor = toSi ? 0.3048 : 1 / 0.3048;
    el.value = String(Number((value * factor).toPrecision(10)));
  });
}

function syncForm(form, eventTarget) {
  const unitSelect = form.elements.unitSystem;
  if (unitSelect) {
    const previous = form.dataset.units || unitSelect.value;
    if (eventTarget === unitSelect) convertUnits(form, previous, unitSelect.value);
    form.dataset.units = unitSelect.value;
    form.querySelectorAll('[data-unit]').forEach((el) => {
      el.textContent = unitSelect.value === 'si' ? el.dataset.si : el.dataset.us;
    });
    form.querySelectorAll('[data-unit-badge]').forEach((el) => {
      el.textContent = unitSelect.value === 'si' ? 'SI units' : 'US customary';
    });
  }
  if (form.dataset.calc === 'ssd') {
    const method = form.elements.method.value;
    form.querySelectorAll('[data-mode]').forEach((field) => { field.hidden = field.dataset.mode !== method; });
  }
  if (form.dataset.calc === 'horizontal') {
    form.querySelector('[data-radius-field]').hidden = form.elements.solveMode.value === 'radius';
  }
}

restore();

FORMS.forEach((form) => {
  prepareFieldAccessibility(form);
  form.dataset.units = form.elements.unitSystem?.value || '';
  syncForm(form);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    calculate(form);
    save();
  });
  form.addEventListener('change', (event) => {
    syncForm(form, event.target);
    clearErrors(form);
    idle(form);
    save();
  });
  form.addEventListener('input', () => {
    clearErrors(form);
    idle(form);
    save();
  });
  form.querySelector('[data-reset]')?.addEventListener('click', () => {
    form.reset();
    form.dataset.units = form.elements.unitSystem?.value || '';
    syncForm(form);
    clearErrors(form);
    idle(form);
    save();
    form.querySelector('input, select')?.focus();
  });
});

// Native details/summary is the primary behavior. This small fallback keeps
// keyboard toggling deterministic in embedded and automation browsers.
document.querySelectorAll('.transport-details summary').forEach((summary) => {
  summary.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    summary.parentElement.open = !summary.parentElement.open;
  });
});
