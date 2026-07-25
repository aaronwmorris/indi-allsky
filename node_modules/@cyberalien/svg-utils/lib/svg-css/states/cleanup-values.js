import { getStateValue } from "./value.js";
/**
* Clean up state values object
*/
function cleanupStateValues(states, values, clone = false) {
	const result = clone ? { ...values } : values;
	for (const state of states) {
		const stateName = typeof state === "string" ? state : state[0];
		result[stateName] = getStateValue(state, result[stateName]);
	}
	return result;
}
export { cleanupStateValues };
