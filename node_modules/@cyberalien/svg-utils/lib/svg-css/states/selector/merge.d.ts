import { StateSelectorData } from "./types.js";
/**
 * Merge sets of StateSelectorData into one
 */
declare function mergeSelectorsForStates(data: StateSelectorData[]): StateSelectorData | null;
export { mergeSelectorsForStates };