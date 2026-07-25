import { CSSGeneratedStylesheet, CSSRules } from "./types.js";
/**
 * Create empty stylesheet
 */
declare function createEmptyStylesheet(): CSSGeneratedStylesheet;
/**
 * Add generated selector to stylesheet
 */
declare function addGeneratedSelector(stylesheet: CSSGeneratedStylesheet, tree: string[], rules: CSSRules | string): void;
/**
 * Stringify generated stylesheet to CSS string
 */
declare function stringifyStylesheet(stylesheet: CSSGeneratedStylesheet, legacyCSS?: boolean): string;
export { addGeneratedSelector, createEmptyStylesheet, stringifyStylesheet };