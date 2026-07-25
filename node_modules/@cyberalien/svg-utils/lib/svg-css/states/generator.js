import { getAdvancedStateDefaultValue } from "./value.js";
/**
* Generate code for object from states
*
* Does not include starting { and ending }
* Last entry does not have a comma at the end
*/
function generateObjectFromStates(states) {
	const lines = [];
	for (const state of states) if (typeof state === "string") lines.push(`'${state}': false`);
	else lines.push(`'${state[0]}': '${getAdvancedStateDefaultValue(state)}'`);
	return lines.join(",\n	");
}
/**
* Generate code for TypeScript interface from state
*/
function getStateInterface(state, optional = true) {
	const q = optional ? "?" : "";
	return typeof state === "string" ? `'${state}'${q}: boolean;` : `'${state[0]}'${q}: ${state[1].map((value) => `'${value}'`).join(" | ")};`;
}
/**
* Generate code for TypeScript interface from states
*
* Does not include starting { and ending }
*/
function generateInterfaceFromStates(states, optional = true) {
	return states.map((state) => getStateInterface(state, optional)).join("\n	");
}
export { generateInterfaceFromStates, generateObjectFromStates, getStateInterface };
