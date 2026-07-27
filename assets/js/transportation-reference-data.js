/* North Bay Digital Foundry — transportation reference metadata.
   Reference data is intentionally isolated from calculator functions.
   No proprietary AASHTO, HCM, or ITE lookup tables are embedded. */

export const TRANSPORTATION_REFERENCES = Object.freeze({
  ssd: {
    title: 'Stopping sight distance',
    source: 'FHWA-RD-02-045, IHSDM Intersection Diagnostic Review Model (2003), eq. 3.5.1; dimensional kinematics.',
    edition: 'FHWA, March 2003',
    kind: 'Direct equation'
  },
  horizontalCurve: {
    title: 'Horizontal curve point-mass relationship',
    source: 'FHWA-HRT-17-098, Self-Enforcing Roadways: A Guidance Report (2018), figs. 32 and 75–78.',
    edition: 'FHWA, January 2018',
    kind: 'Direct equation'
  },
  verticalCurve: {
    title: 'Vertical curve K-value method',
    source: 'AASHTO-based relation A = |g₂ − g₁| and L = KA; K is supplied by the user.',
    edition: 'User-selected governing edition',
    kind: 'Direct equation with user-supplied criterion'
  },
  pavement: {
    title: 'Flexible pavement structural number',
    source: 'AASHTO Guide for Design of Pavement Structures (1993), flexible pavement design equation; reproduced in FHWA NHI-05-037 (2006), ch. 3.',
    edition: 'AASHTO 1993 / FHWA NHI-05-037 (2006)',
    kind: 'Implicit empirical equation'
  },
  los: {
    title: 'Intersection delay classification',
    source: 'FHWA-HOP-08-024, Traffic Signal Timing Manual (2008), table 3-3; unsignalized thresholds documented in FHWA project environmental analyses using HCM control-delay ranges.',
    edition: 'FHWA 2008 / HCM-aligned screening thresholds',
    kind: 'Small, source-versioned threshold table'
  },
  sightTriangle: {
    title: 'Stop-controlled departure sight triangle',
    source: 'AASHTO-based time-gap relationship ISD = 1.47Vt (US customary); time gap is supplied by the user.',
    edition: 'User-selected governing AASHTO edition',
    kind: 'Direct equation with user-supplied criterion'
  },
  tripGeneration: {
    title: 'Trip generation',
    source: 'ITE-based workflow using only a user-supplied or otherwise authorized rate. No ITE rates or equations are bundled.',
    edition: 'User-supplied source and edition',
    kind: 'Manual-rate adapter'
  }
});

// Seconds per vehicle. These are classification thresholds only; this suite
// does not calculate HCM control delay.
export const LOS_THRESHOLDS = Object.freeze({
  signalized: Object.freeze([10, 20, 35, 55, 80]),
  twsc: Object.freeze([10, 15, 25, 35, 50]),
  awsc: Object.freeze([10, 15, 25, 35, 50])
});

export const TRIP_DATA_SCHEMA = Object.freeze({
  id: 'custom',
  name: 'Custom land use',
  code: null,
  independentVariable: 'user-selected',
  periods: ['am', 'pm'],
  methods: ['average-rate'],
  source: 'User supplied',
  edition: 'User supplied'
});
