/**
 * Theme constants and the pre-hydration initialisation script.
 *
 * The script runs blocking in `<head>` so the resolved theme is on `<html>` before first paint.
 * Applying it from an effect instead means the first paint always uses the classless CSS default
 * (dark), and every light-theme user sees a flash on every full page load.
 */

export type Theme = 'dark' | 'light' | 'system';

/** Where the user's explicit preference is persisted. Shared by the script and the provider. */
export const THEME_STORAGE_KEY = 'lrn-ui-theme';

/**
 * Resolve and apply the theme class before first paint.
 *
 * A compile-time constant with no interpolation — nothing from a request, a user or the network
 * reaches it. Deliberately tolerant: a browser that blocks storage access falls through to the
 * classless dark default rather than throwing before the page renders.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem('${THEME_STORAGE_KEY}');var t=(s==='light'||s==='dark')?s:(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');var e=document.documentElement;e.classList.remove('light','dark');e.classList.add(t);}catch(e){}})();`;
