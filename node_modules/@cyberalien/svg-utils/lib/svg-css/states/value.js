/**
* Get default value for advanced state
*/
function getAdvancedStateDefaultValue(state) {
	return state.length === 3 ? state[2] : state[1][0];
}
/**
* Get value for state
*/
function getStateValue(state, value) {
	if (typeof state === "string") return !!value && value !== "false" && value !== "0";
	return typeof value !== "string" || !state[1].includes(value) ? getAdvancedStateDefaultValue(state) : value;
}
export { getAdvancedStateDefaultValue, getStateValue };
