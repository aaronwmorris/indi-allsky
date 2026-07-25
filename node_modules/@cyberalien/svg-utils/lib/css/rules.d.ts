import { CSSRules } from "./types.js";
/**
 * Split rules string into object
 */
declare function splitCSSRules(rules: CSSRules | string): CSSRules;
/**
 * Merge rules
 */
declare function mergeCSSRules(rules: CSSRules | string, oldRules?: CSSRules | string): CSSRules;
export { mergeCSSRules, splitCSSRules };