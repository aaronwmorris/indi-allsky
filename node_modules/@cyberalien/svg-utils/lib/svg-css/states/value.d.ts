import { IconStatesAdvancedState, IconStatesState } from "./types.js";
/**
 * Get default value for advanced state
 */
declare function getAdvancedStateDefaultValue(state: IconStatesAdvancedState): string;
/**
 * Get value for state
 */
declare function getStateValue(state: IconStatesState, value?: string | boolean | undefined): string | boolean;
export { getAdvancedStateDefaultValue, getStateValue };