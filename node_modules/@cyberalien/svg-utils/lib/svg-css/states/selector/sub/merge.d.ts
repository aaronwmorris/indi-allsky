import { StateSelectorSubParts } from "../types.js";
/**
 * Merge multiple selector parts into one
 */
declare function mergeMultipleSelectorSubParts(parts: StateSelectorSubParts[]): StateSelectorSubParts | null;
export { mergeMultipleSelectorSubParts };