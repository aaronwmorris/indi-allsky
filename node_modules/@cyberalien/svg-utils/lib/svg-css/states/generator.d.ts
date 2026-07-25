import { IconStatesList, IconStatesState } from "./types.js";
/**
 * Generate code for object from states
 *
 * Does not include starting { and ending }
 * Last entry does not have a comma at the end
 */
declare function generateObjectFromStates(states: IconStatesList): string;
/**
 * Generate code for TypeScript interface from state
 */
declare function getStateInterface(state: IconStatesState, optional?: boolean): string;
/**
 * Generate code for TypeScript interface from states
 *
 * Does not include starting { and ending }
 */
declare function generateInterfaceFromStates(states: IconStatesList, optional?: boolean): string;
export { generateInterfaceFromStates, generateObjectFromStates, getStateInterface };