import { ConvertSVGPropertyToCSSOptions } from "./types.js";
/**
 * Convert property to CSS
 */
declare function convertSVGPropertyToCSS(tag: string, prop: string, value: string | number, options?: ConvertSVGPropertyToCSSOptions): [string, string] | undefined;
export { convertSVGPropertyToCSS };