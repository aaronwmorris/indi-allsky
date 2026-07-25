import { StateSelectorParts } from "../types.js";
/**
 * Merge all selectors
 *
 * Returns null if merge is not possible
 *
 * If multiple results are returned, all have identical at-rules and svg selectors, but different parent selectors.
 */
declare function mergeSelectorParts(parts: StateSelectorParts[]): StateSelectorParts[] | null;
export { mergeSelectorParts };