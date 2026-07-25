import { ConvertSVGContentOptions, ConvertedSVGContent } from "./types.js";
/**
 * Convert SVG content string to SVG+CSS
 */
declare function convertSVGContentToCSSRules(content: string, options: ConvertSVGContentOptions): ConvertedSVGContent;
export { convertSVGContentToCSSRules };