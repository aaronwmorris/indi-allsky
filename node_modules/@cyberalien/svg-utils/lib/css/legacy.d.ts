import { CSSGeneratedStylesheet } from "./types.js";
/**
 * Merge selectors for backwards compatibility with legacy CSS structure: no nested CSS
 */
declare function mergeLegacyCSS(stylesheet: CSSGeneratedStylesheet): CSSGeneratedStylesheet;
export { mergeLegacyCSS };