import { StateSelectorParts } from "../types.js";
/**
 * Convert selector parts to array of strings
 *
 * Assumes that all parts have identical at-rules and svg selectors, but different parent selectors,
 * same as returned by mergeSelectorParts()
 */
declare function stringifySelectorParts(parts: StateSelectorParts[]): string[] | null;
export { stringifySelectorParts };