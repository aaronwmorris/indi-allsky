import { IconStatesList } from "./types.js";
/**
 * Clean up state values object
 */
declare function cleanupStateValues(states: IconStatesList, values: Record<string, boolean | string>, clone?: boolean): Record<string, string | boolean>;
export { cleanupStateValues };