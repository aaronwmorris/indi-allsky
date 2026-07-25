import { IconStatesList } from "./types.js";
/**
 * Create reactive object from states
 */
declare function getObjectFromStates(states: IconStatesList): Record<string, boolean | string>;
export { getObjectFromStates };