import { IconSet } from "../icon-set/index.js";
/**
 * Detect palette
 *
 * Returns null if icon set has mixed colors
 */
declare function detectIconSetPalette(iconSet: IconSet): boolean | null;
export { detectIconSetPalette };