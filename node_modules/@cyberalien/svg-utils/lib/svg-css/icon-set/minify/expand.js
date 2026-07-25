import { expandItem } from "../../../helpers/data/expand.js";
import { iconSetMinifySimpleKeys, iconSetMinifyStatefulKeys } from "./keys.js";
/**
* Expand class content from icon set
*/
function expandSVGCSSIconSetClass(css, classContent) {
	for (const prop of iconSetMinifySimpleKeys) if (css[prop]) expandItem(css[prop], classContent, prop);
	for (const prop of iconSetMinifyStatefulKeys) {
		const value = classContent[prop];
		const list = css[prop];
		if (list && value) for (const state in value) expandItem(list, value, state);
	}
}
/**
* Expand fallback prefix
*/
function expandSVGCSSIconSetFallback(iconSet) {
	const fallbackPrefix = iconSet.fallbackPrefix ?? "";
	if (fallbackPrefix) {
		delete iconSet.fallbackPrefix;
		for (const iconName in iconSet.icons) {
			const icon = iconSet.icons[iconName];
			const fallback = icon.fallback;
			if (fallback) icon.fallback = fallbackPrefix + fallback;
		}
	}
}
/**
* Unminify icon set
*/
function expandSVGCSSIconSet(iconSet) {
	const { viewBoxes, statesList, css } = iconSet;
	expandSVGCSSIconSetFallback(iconSet);
	if (viewBoxes || statesList) {
		for (const iconName in iconSet.icons) {
			const icon = iconSet.icons[iconName];
			if (viewBoxes) expandItem(viewBoxes, icon, "viewBox");
			if (statesList) expandItem(statesList, icon, "states");
		}
		delete iconSet.viewBoxes;
		delete iconSet.statesList;
	}
	if (css && iconSet.classes) {
		for (const className in iconSet.classes) expandSVGCSSIconSetClass(css, iconSet.classes[className]);
		delete iconSet.css;
	}
}
export { expandSVGCSSIconSet, expandSVGCSSIconSetClass, expandSVGCSSIconSetFallback };
