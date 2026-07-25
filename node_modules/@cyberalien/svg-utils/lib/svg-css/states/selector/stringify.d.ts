import { StateSelectorData } from "./types.js";
/**
 * Convert selector data to strings
 *
 * Returns sets of selector sequences
 */
declare function stringifySelectorsForState(data: StateSelectorData): string[][] | null;
export { stringifySelectorsForState };