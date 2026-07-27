import test from 'node:test';
import assert from 'node:assert/strict';
import {
  stoppingSightDistance,
  horizontalCurve,
  verticalCurve,
  pavementStructuralNumber,
  intersectionScreening,
  sightTriangle,
  tripGeneration
} from '../assets/js/transportation-engineering.js';

const close = (actual, expected, tolerance = 1e-6) =>
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} not within ${tolerance} of ${expected}`);

test('SSD components, downgrade sign, and US/SI equivalence', () => {
  const level = stoppingSightDistance({ unitSystem: 'us', speed: 60, reactionTime: 2.5, gradePct: 0, method: 'deceleration', deceleration: 11.2, friction: 0.35 });
  close(level.reactionDistance, 220, 0.01);
  close(level.brakingDistance, 345.7143, 0.02);
  const downgrade = stoppingSightDistance({ unitSystem: 'us', speed: 60, reactionTime: 2.5, gradePct: -5, method: 'deceleration', deceleration: 11.2, friction: 0.35 });
  assert.ok(downgrade.totalDistance > level.totalDistance);
  const si = stoppingSightDistance({ unitSystem: 'si', speed: 96.56064, reactionTime: 2.5, gradePct: 0, method: 'deceleration', deceleration: 3.41376, friction: 0.35 });
  close(si.totalDistance / 0.3048, level.totalDistance, 1e-6);
  assert.equal(stoppingSightDistance({ unitSystem: 'us', speed: Infinity, reactionTime: 2.5, gradePct: 0, method: 'friction', friction: 0.3 }).isValid, false);
});

test('horizontal solve modes are algebraic inverses', () => {
  const radius = horizontalCurve({ unitSystem: 'us', speed: 50, solveMode: 'radius', superelevationPct: 6, friction: 0.12 });
  const e = horizontalCurve({ unitSystem: 'us', speed: 50, solveMode: 'superelevation', superelevationPct: 6, friction: 0.12, radius: radius.radius });
  const f = horizontalCurve({ unitSystem: 'us', speed: 50, solveMode: 'friction', superelevationPct: 6, friction: 0.12, radius: radius.radius });
  close(e.requiredSuperelevationPct, 6, 1e-9);
  close(f.requiredFriction, 0.12, 1e-9);
  assert.equal(horizontalCurve({ unitSystem: 'us', speed: NaN, solveMode: 'radius', superelevationPct: 0, friction: 0 }).isValid, false);
});

test('vertical curve uses absolute algebraic grade difference and minimum', () => {
  const result = verticalCurve({ unitSystem: 'us', curveType: 'crest', speed: 45, g1Pct: 2, g2Pct: -3, kValue: 44, minimumLength: 250 });
  assert.equal(result.gradeDifferencePct, 5);
  assert.equal(result.calculatedLength, 220);
  assert.equal(result.finalLength, 250);
  assert.equal(verticalCurve({ unitSystem: 'us', curveType: 'sag', speed: 40, g1Pct: 1, g2Pct: 1, kValue: 30, minimumLength: 0 }).isValid, false);
});

test('pavement bisection converges and substitutes into original equation', () => {
  const input = { w18: 1_000_000, reliabilityPct: 95, standardDeviation: 0.45, initialServiceability: 4.2, terminalServiceability: 2.5, resilientModulusPsi: 10_000, zR: -1.645, tolerance: 1e-8, snMax: 20 };
  const result = pavementStructuralNumber(input);
  assert.equal(result.isValid, true);
  assert.equal(result.converged, true);
  close(result.rhs, Math.log10(input.w18), 1e-7);
  assert.equal(pavementStructuralNumber({ ...input, w18: 1e30, snMax: 0.1 }).isValid, false);
  assert.equal(pavementStructuralNumber({ ...input, resilientModulusPsi: Infinity }).isValid, false);
});

test('LOS classifications honor threshold boundaries and controlling v/c', () => {
  const result = intersectionScreening({
    controlType: 'signalized', periodMinutes: 60, peakHourFactor: 1, alertRatio: 0.9,
    approaches: [
      { name: 'Northbound', demand: 900, capacity: 1000, delay: 10, lanes: 'L1 / T1 / R0' },
      { name: 'Southbound', demand: 1100, capacity: 1000, delay: 20.01, lanes: 'L1 / T1 / R0' }
    ]
  });
  assert.equal(result.approaches[0].los, 'A');
  assert.equal(result.approaches[1].los, 'C');
  assert.equal(result.controllingApproach, 'Southbound');
  assert.equal(result.approaches[1].capacityFlag, 'Demand exceeds assumed capacity');
});

test('sight triangle uses time gap and equivalent unit conversion', () => {
  const us = sightTriangle({ unitSystem: 'us', speed: 50, majorGradePct: 0, minorGradePct: 0, lanes: 2, laneWidth: 12, medianWidth: 0, setback: 14.5, timeGap: 7.5, vehicle: 'Passenger car' });
  close(us.majorLeg, 1.4666666667 * 50 * 7.5, 0.01);
  const si = sightTriangle({ unitSystem: 'si', speed: 80.4672, majorGradePct: 0, minorGradePct: 0, lanes: 2, laneWidth: 3.6576, medianWidth: 0, setback: 4.4196, timeGap: 7.5, vehicle: 'Passenger car' });
  close(si.majorLeg / 0.3048, us.majorLeg, 1e-6);
});

test('trip rate, split, and sequential adjustments remain transparent', () => {
  const result = tripGeneration({ landUse: 'Custom', source: 'Authorized local study', edition: '2026', variableType: 'dwelling-units', method: 'average-rate', period: 'pm', quantity: 100, rate: 1.2, enteringPct: 60, exitingPct: 40, passByPct: 10, divertedPct: 5, internalPct: 20 });
  assert.equal(result.rawTrips, 120);
  close(result.adjustedTrips, 82.08);
  close(result.enteringTrips, 49.248);
  close(result.passByReduction, 12);
  assert.equal(tripGeneration({ ...result, quantity: -1 }).isValid, false);
});
