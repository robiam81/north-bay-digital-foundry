/* =========================================================================
   North Bay Digital Foundry — Storm Drainage Toolkit
   UI / state layer (ES module).

   Responsibilities: DOM wiring, per-keystroke validation display, result
   rendering, and localStorage persistence. All engineering math lives in
   storm-engineering.js and is imported here — no formulas in this file.

   Output safety: every calculated value reaches the page via textContent;
   no innerHTML is used anywhere in this module.
   ========================================================================= */

import {
  rationalMethod,
  pipeSizing,
  inletCapacity,
  detentionBasin,
  outletStructure,
  culvertScreening,
  riprapApron
} from './storm-engineering.js';

/* --- Calculator registry: form[data-calc] → pure engineering function --- */
const CALCS = {
  rationalMethod,
  pipeSizing,
  inletCapacity,
  detentionBasin,
  outletStructure,
  culvertScreening,
  riprapApron
};

/* --- Flag code → chip label + modifier class --------------------------- */
const FLAGS = {
  ok:      { label: 'OK',        cls: 'nbdf-chip--ok' },
  info:    { label: 'INFO',      cls: 'nbdf-chip--info' },
  review:  { label: 'REVIEW',    cls: 'nbdf-chip--review' },
  exceeds: { label: 'EXCEEDS',   cls: 'nbdf-chip--exceeds' }
};

const STORAGE_KEY = 'nbdf_v1_storm_drainage_calc';
const STORAGE_VERSION = 1;

/* Persisted text lists (comma-separated numbers) must stay plain */
const LIST_PATTERN = /^[0-9\s.,]*$/;

/* =========================================================================
   Formatting (display only — engineering values are never rounded upstream)
   ========================================================================= */

/**
 * Format a numeric result for display with magnitude-appropriate precision.
 * @param {number} v
 * @returns {string}
 */
function fmt(v) {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (a >= 100) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

/* =========================================================================
   Field-level validation display
   ========================================================================= */

/**
 * Show or clear the inline error for one input.
 * @param {HTMLInputElement|HTMLSelectElement} el
 * @param {string|null} message Null clears the error.
 */
function setFieldError(el, message) {
  const field = el.closest('.nbdf-field');
  const errEl = field && field.querySelector('.nbdf-field__error');
  if (!errEl) return;
  if (message) {
    errEl.textContent = message;
    errEl.hidden = false;
    el.setAttribute('aria-invalid', 'true');
  } else {
    errEl.textContent = '';
    errEl.hidden = true;
    el.removeAttribute('aria-invalid');
  }
}

/**
 * Inputs/selects that participate in the current computation (mode-switched
 * calculators hide the fields that belong to the other mode).
 * @param {HTMLFormElement} form
 * @returns {(HTMLInputElement|HTMLSelectElement)[]}
 */
function activeFields(form) {
  return Array.from(form.querySelectorAll('input[name], select[name]'))
    .filter((el) => {
      const field = el.closest('.nbdf-field');
      return !(field && field.hidden);
    });
}

/* =========================================================================
   Result rendering
   ========================================================================= */

/**
 * Reset every readout, chip, and note in a calculator card to idle.
 * @param {Element} card
 */
function clearResults(card) {
  card.querySelectorAll('[data-out]').forEach((el) => { el.textContent = '—'; });
  card.querySelectorAll('[data-flag]').forEach((el) => { el.hidden = true; });
  card.querySelectorAll('[data-flag-msg]').forEach((el) => {
    el.hidden = true;
    el.textContent = '';
  });
}

/**
 * Render a successful engineering result into a calculator card.
 * Numeric outputs are formatted; string outputs (e.g. the controlling
 * condition) are shown verbatim via textContent.
 * @param {Element} card
 * @param {Object} result Result object from the engineering layer.
 */
function renderResults(card, result) {
  card.querySelectorAll('[data-out]').forEach((el) => {
    const value = result[el.dataset.out];
    if (typeof value === 'number') el.textContent = fmt(value);
    else if (typeof value === 'string') el.textContent = value;
    else el.textContent = '—';
  });

  const chip = card.querySelector('[data-flag]');
  const note = card.querySelector('[data-flag-msg]');
  const flag = FLAGS[result.flag];
  if (chip) {
    if (flag) {
      chip.hidden = false;
      chip.textContent = flag.label;
      chip.className = 'nbdf-chip ' + flag.cls;
    } else {
      chip.hidden = true;
    }
  }
  if (note) {
    if (typeof result.flagMessage === 'string' && result.flagMessage) {
      note.hidden = false;
      note.textContent = result.flagMessage;
    } else {
      note.hidden = true;
      note.textContent = '';
    }
  }
}

/* =========================================================================
   Compute pipeline: read form → validate → engineering fn → render
   ========================================================================= */

/**
 * Validate a form's inputs and run its calculator. Runs on every input
 * event, so incomplete forms simply idle (no error spam on empty fields).
 * Text inputs (comma-separated lists) pass their raw string through; the
 * engineering layer parses and validates them.
 * @param {HTMLFormElement} form
 */
function compute(form) {
  const fn = CALCS[form.dataset.calc];
  const card = form.closest('.nbdf-calc');
  if (!fn || !card) return;

  const values = {};
  let incomplete = false;
  let unparseable = false;

  activeFields(form).forEach((el) => {
    if (el.tagName === 'SELECT') {
      values[el.name] = el.value;
      return;
    }
    const raw = el.value.trim();
    if (el.type === 'text') {
      if (raw === '') {
        setFieldError(el, null);
        incomplete = true;
        return;
      }
      values[el.name] = raw;
      return;
    }
    if (el.validity.badInput) {
      setFieldError(el, 'Enter a number.');
      unparseable = true;
      return;
    }
    if (raw === '') {
      setFieldError(el, null);
      incomplete = true;
      return;
    }
    values[el.name] = Number(raw);
  });

  if (unparseable || incomplete) {
    clearResults(card);
    return;
  }

  const result = fn(values);
  if (!result.isValid) {
    const flagged = new Set();
    result.errors.forEach((err) => {
      const el = form.querySelector('[name="' + err.field + '"]');
      if (el && !flagged.has(err.field)) {
        setFieldError(el, err.message);
        flagged.add(err.field);
      }
    });
    activeFields(form).forEach((el) => {
      if (!flagged.has(el.name)) setFieldError(el, null);
    });
    clearResults(card);
    return;
  }

  activeFields(form).forEach((el) => setFieldError(el, null));
  renderResults(card, result);
}

/* =========================================================================
   Solve-for / type modes: show only the fields the selected mode needs
   ========================================================================= */

/**
 * @param {HTMLFormElement} form
 */
function syncModeVisibility(form) {
  const select = form.querySelector('select[name="mode"]');
  if (!select) return;
  form.querySelectorAll('.nbdf-field[data-mode]').forEach((field) => {
    const hidden = field.dataset.mode !== select.value;
    field.hidden = hidden;
    if (hidden) {
      const input = field.querySelector('input[name]');
      if (input) setFieldError(input, null);
    }
  });
}

/* =========================================================================
   Persistence — localStorage key `nbdf_v1_storm_drainage_calc`
   ========================================================================= */

/** Persist the raw string value of every named input, keyed by element id. */
function saveState() {
  const values = {};
  document.querySelectorAll('.nbdf-form input[name], .nbdf-form select[name]')
    .forEach((el) => {
      if (el.id) values[el.id] = el.value;
    });
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, values }));
  } catch (e) { /* storage unavailable (private mode / quota) — non-fatal */ }
}

/**
 * Restore persisted values. Every restored entry is validated before being
 * applied: it must target a known field id, be a short string, and either
 * parse to a finite number (numeric inputs), match the list pattern (text
 * list inputs), or match an existing option (selects). Anything else is
 * discarded.
 */
function restoreState() {
  let parsed = null;
  try {
    parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch (e) {
    return;
  }
  if (!parsed || parsed.version !== STORAGE_VERSION || typeof parsed.values !== 'object' || parsed.values === null) {
    return;
  }

  Object.keys(parsed.values).forEach((id) => {
    const el = document.getElementById(id);
    if (!el || !el.closest('.nbdf-form') || !el.name) return;
    const value = parsed.values[id];
    if (typeof value !== 'string' || value.length > 80) return;

    if (el.tagName === 'SELECT') {
      const valid = Array.from(el.options).some((opt) => opt.value === value);
      if (valid) el.value = value;
      return;
    }
    if (el.type === 'text') {
      if (LIST_PATTERN.test(value)) el.value = value;
      return;
    }
    if (value === '' || (value.length <= 40 && Number.isFinite(Number(value)))) {
      el.value = value;
    }
  });
}

/* =========================================================================
   Wiring
   ========================================================================= */

function init() {
  const forms = Array.from(document.querySelectorAll('form.nbdf-form[data-calc]'));

  restoreState();

  forms.forEach((form) => {
    // Calculators never navigate; results render in place.
    form.addEventListener('submit', (e) => e.preventDefault());

    form.addEventListener('input', (e) => {
      if (e.target.name === 'mode') syncModeVisibility(form);
      compute(form);
      saveState();
    });

    syncModeVisibility(form);
    compute(form);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
