import { CSSHashOptions, CSSRules } from "./types.js";
/**
 * Get class name for CSS rules
 */
declare function createCSSClassName(rules: CSSRules, options: CSSHashOptions): string;
export { createCSSClassName };