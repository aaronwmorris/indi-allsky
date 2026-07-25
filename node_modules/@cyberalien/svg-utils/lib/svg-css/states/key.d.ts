import { IconStatesList } from "./types.js";
/**
 * Get state values from an underscore separated list of state values
 */
declare function getStatesFromKey(key: string, states: IconStatesList): Record<string, string | boolean>;
export { getStatesFromKey };