// eslint-config-next 16 ships native flat config arrays, so they are spread directly rather
// than bridged through FlatCompat.
import coreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

const config = [
  { ignores: ['.next/**', 'node_modules/**', 'coverage/**', 'playwright-report/**'] },
  ...coreWebVitals,
  ...nextTypescript,
];

export default config;
