import { getStatesFromKey } from "../key.js";
import { mergeSelectorsForStates } from "./merge.js";
import { splitSelectorsForState } from "./split.js";
import { stringifySelectorsForState } from "./stringify.js";
/**
* Create context object from config
*/
function createStatefulIconSelectorsContext(config, states, staticClassname) {
	return {
		config,
		states,
		staticClassname,
		data: Object.create(null),
		parsed: Object.create(null)
	};
}
/**
* Get selectors to render state values
*
* Does not include shape class name
*/
function getSelectorsForStateValues(context, value) {
	const dataToMerge = [];
	let cacheKey = "";
	const { config, states, data, parsed } = context;
	const stateValues = typeof value === "string" ? getStatesFromKey(value, states) : value;
	const add = (key, value) => {
		cacheKey += `${key}:${value};`;
		const baseStateItem = config[key];
		const stateItem = typeof baseStateItem === "object" && !Array.isArray(baseStateItem) ? baseStateItem[value] : baseStateItem;
		if (!stateItem) return false;
		let selectorData;
		if (typeof stateItem === "string") {
			const selector = stateItem.replace("{state}", value);
			if (data[selector]) selectorData = data[selector];
			else if (data[selector] === null) return false;
			else {
				const split = splitSelectorsForState(selector);
				data[selector] = split;
				if (!split) return false;
				selectorData = split;
			}
		} else selectorData = stateItem;
		dataToMerge.push(selectorData);
		return true;
	};
	for (const stateName in stateValues) {
		const stateValue = stateValues[stateName];
		const stateItem = states.find((s) => typeof s === "string" ? s === stateName : s[0] === stateName);
		if (!stateItem) return null;
		if (typeof stateItem === "string") {
			if (stateValue && !add(stateName, stateName)) return null;
		} else {
			const allValues = stateItem[1];
			if (typeof stateValue !== "string" || !allValues.includes(stateValue)) return null;
			if (stateValue !== (stateItem[2] || allValues[0]) && !add(stateName, stateValue)) return null;
		}
	}
	if (!dataToMerge.length) return [[]];
	if (parsed[cacheKey] !== void 0) return parsed[cacheKey];
	let merged = data[cacheKey];
	if (!merged) {
		if (merged !== null) {
			merged = mergeSelectorsForStates(dataToMerge);
			data[cacheKey] = merged;
		}
		if (!merged) return null;
	}
	const stringified = stringifySelectorsForState(merged);
	parsed[cacheKey] = stringified;
	return stringified;
}
export { createStatefulIconSelectorsContext, getSelectorsForStateValues };
