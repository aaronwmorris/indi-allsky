import { CSSRules } from "../css/types.js";
import { ParsedXMLTagElement } from "../xml/types.js";
import { BaseConvertSVGContentOptions } from "./types.js";
/**
 * Convert SVG tags tree to SVG+CSS
 *
 * Returns used CSS class names with rules
 */
declare function convertSVGRootToCSS(root: ParsedXMLTagElement[], options: BaseConvertSVGContentOptions): Record<string, CSSRules>;
export { convertSVGRootToCSS };