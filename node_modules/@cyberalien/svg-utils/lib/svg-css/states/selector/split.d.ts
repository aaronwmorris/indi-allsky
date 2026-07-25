import { StateSelectorData } from "./types.js";
/**
 * Split comma separated selectors into parts, group by compatibility so later can be merged
 */
declare function splitSelectorsForState(selectors: string): StateSelectorData | null;
export { splitSelectorsForState };