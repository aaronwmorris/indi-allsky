import { iconSetMinifyKeys, iconSetMinifySimpleKeys, iconSetMinifyStatefulKeys } from "./keys.js";
import { stringifyIconViewBox } from "../../../svg/viewbox/value.js";
import { compactItem, createCompactContext } from "../../../helpers/data/compact.js";
/**
* Create context for minification
*/
function createIconSetMinifyContext() {
	const result = Object.create(null);
	for (const key of iconSetMinifyKeys) result[key] = createCompactContext();
	result.viewBox = createCompactContext();
	result.states = createCompactContext();
	return result;
}
/**
* Get key for viewBox
*/
function viewBoxKey(viewBox) {
	return typeof viewBox === "string" ? viewBox : stringifyIconViewBox(viewBox) + ("cx" in viewBox ? ` ${viewBox.cx}` : "");
}
/**
* Minify icon set
*/
function minifySVGCSSIconSet(iconSet) {
	const context = createIconSetMinifyContext();
	const viewBoxes = context.viewBox;
	const statesList = context.states;
	if (iconSet.viewBoxes) viewBoxes.data = [...iconSet.viewBoxes];
	viewBoxes.data.forEach((value, index) => {
		const key = viewBoxKey(value);
		viewBoxes.map.set(key, index);
	});
	if (iconSet.statesList) statesList.data = [...iconSet.statesList];
	statesList.data.forEach((value, index) => {
		const key = JSON.stringify(value);
		statesList.map.set(key, index);
	});
	for (const prop of iconSetMinifyKeys) {
		context[prop].data = [...iconSet.css?.[prop] ?? []];
		const { data, map } = context[prop];
		data.forEach((value, index) => {
			map.set(value, index);
		});
	}
	if (!iconSet.fallbackPrefix) {
		let commonPrefix;
		for (const iconName in iconSet.icons) {
			const fallback = iconSet.icons[iconName].fallback;
			if (fallback) {
				const parts = fallback.split(":");
				if (parts.length !== 2) {
					commonPrefix = null;
					break;
				}
				const prefix = parts[0];
				if (commonPrefix === void 0) commonPrefix = prefix;
				else if (commonPrefix !== prefix) {
					commonPrefix = null;
					break;
				}
			}
		}
		if (commonPrefix) {
			iconSet.fallbackPrefix = `${commonPrefix}:`;
			for (const iconName in iconSet.icons) {
				const icon = iconSet.icons[iconName];
				const fallback = icon.fallback;
				if (fallback) icon.fallback = fallback.slice(commonPrefix.length + 1);
			}
		}
	}
	for (const iconName in iconSet.icons) {
		const icon = iconSet.icons[iconName];
		const viewBoxValue = icon.viewBox;
		if (typeof viewBoxValue !== "number") compactItem(viewBoxes, viewBoxKey(viewBoxValue), icon, "viewBox", viewBoxValue);
		const statesValue = icon.states;
		if (typeof statesValue !== "number" && statesValue?.length) compactItem(statesList, JSON.stringify(statesValue), icon, "states", statesValue);
	}
	if (iconSet.classes) for (const className in iconSet.classes) {
		const classContent = iconSet.classes[className];
		for (const prop of iconSetMinifySimpleKeys) if (typeof classContent[prop] === "string") compactItem(context[prop], classContent[prop], classContent, prop);
		for (const prop of iconSetMinifyStatefulKeys) {
			const value = classContent[prop];
			if (value) {
				for (const state in value) if (typeof value[state] === "string") compactItem(context[prop], value[state], value, state);
			}
		}
	}
	iconSet.viewBoxes = viewBoxes.data.length ? viewBoxes.data : void 0;
	iconSet.statesList = statesList.data.length ? statesList.data : void 0;
	delete iconSet.css;
	for (const prop of iconSetMinifyKeys) {
		const data = context[prop].data;
		if (data.length) {
			if (!iconSet.css) iconSet.css = Object.create(null);
			iconSet.css[prop] = data;
		}
	}
}
export { createIconSetMinifyContext, minifySVGCSSIconSet };
