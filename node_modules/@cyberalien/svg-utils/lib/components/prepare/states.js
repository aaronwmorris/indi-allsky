import { getStateValue } from "../../svg-css/states/value.js";
import { createStatefulIconSelectorsContext } from "../../svg-css/states/selector/parse.js";
import { parseIconFallbackTemplate } from "../../svg-css/states/fallback/parse.js";
import { parseViewBox } from "../../svg/viewbox/parse.js";
/**
* Check states for stateful icon
*/
function prepareComponentFactoryStatefulIcon(icon, options) {
	const viewBox = typeof icon.viewBox === "string" ? parseViewBox(icon.viewBox) : icon.viewBox;
	if (!viewBox) return;
	const newIcon = {
		...icon,
		viewBox
	};
	const fallback = icon.fallback;
	const isStatefulFallback = fallback?.includes("{");
	if (!isStatefulFallback && fallback) newIcon.defaultFallback = fallback;
	const allStates = icon.states;
	if (!allStates) return newIcon;
	const config = Object.create(null);
	const customConfig = options?.stateSelectors;
	const supportedStates = /* @__PURE__ */ new Set();
	const defaultStateValues = Object.create(null);
	const supportedStateValues = Object.create(null);
	for (const state of allStates) {
		const stateName = typeof state === "string" ? state : state[0];
		const defaultValue = getStateValue(state);
		defaultStateValues[stateName] = defaultValue;
		if (customConfig?.[stateName]) config[stateName] = customConfig[stateName];
		else {
			if (state === "focus") config[stateName] = `input:not(:disabled):focus-visible, input:not(:disabled):hover, button:not(:disabled):focus-visible, button:not(:disabled):hover, &.state-${stateName}`;
			else config[stateName] = `&.state-{state}`;
			supportedStates.add(stateName);
			supportedStateValues[stateName] = defaultValue;
		}
	}
	const staticClassname = Object.keys(icon.animations ?? {}).length > 0 && options?.staticState !== false ? "state-static" : void 0;
	const statefulData = {
		allStates,
		supportedStates,
		defaultStateValues,
		supportedStateValues,
		staticClassname,
		context: createStatefulIconSelectorsContext(config, allStates, staticClassname)
	};
	if (isStatefulFallback) {
		let fallbackTemplate = parseIconFallbackTemplate(fallback, allStates);
		if (!fallbackTemplate) return newIcon;
		let defaultFallback = "";
		let hasStatefulFallback = false;
		fallbackTemplate = fallbackTemplate.map((item) => {
			if (typeof item === "string") {
				defaultFallback += item;
				return item;
			}
			const stateName = item.state;
			const defaultValue = defaultStateValues[stateName] || stateName;
			defaultFallback += defaultValue;
			if (supportedStates.has(stateName)) {
				hasStatefulFallback = true;
				return item;
			}
			return defaultValue;
		});
		if (hasStatefulFallback) statefulData.fallback = fallbackTemplate;
		newIcon.defaultFallback = defaultFallback;
	}
	return {
		...newIcon,
		statefulData
	};
}
export { prepareComponentFactoryStatefulIcon };
