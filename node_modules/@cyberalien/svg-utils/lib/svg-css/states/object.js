import { getAdvancedStateDefaultValue } from "./value.js";
/**
* Create reactive object from states
*/
function getObjectFromStates(states) {
	const obj = Object.create(null);
	for (const state of states) if (typeof state === "string") obj[state] = false;
	else obj[state[0]] = getAdvancedStateDefaultValue(state);
	return obj;
}
export { getObjectFromStates };
