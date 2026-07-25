import { SVG } from "../svg/index.js";
import { FindColorsResult, ParseColorsOptions } from "./parse.js";
/**
 * Validate colors in icon
 *
 * If icon is monotone,
 *
 * Throws exception on error
 */
declare function validateColors(svg: SVG, expectMonotone: boolean, options?: ParseColorsOptions): FindColorsResult;
export { validateColors };