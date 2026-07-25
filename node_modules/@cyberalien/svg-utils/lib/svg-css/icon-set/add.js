import { stringifyCSSAnimationFrames, stringifyCSSRules } from "../../css/stringify.js";
import { minifyCSS } from "../../css/minify.js";
import { expandSVGCSSIconSetFallback } from "./minify/expand.js";
function minifyRules(value) {
	return (value ? minifyCSS(typeof value === "string" ? value : stringifyCSSRules(value)) : void 0) || void 0;
}
function stringifyObject(data) {
	if (data) {
		const result = Object.create(null);
		for (const key in data) result[key] = minifyCSS(typeof data[key] === "string" ? data[key] : stringifyCSSRules(data[key]));
		return result;
	}
}
/**
* Add icon to an icon set
*/
function addIconToSVGCSSIconSet(iconSet, iconName, icon) {
	const iconData = {
		content: icon.content,
		states: icon.states,
		viewBox: icon.viewBox
	};
	let fallback = icon.fallback;
	if (fallback) {
		const fallbackPrefix = iconSet.fallbackPrefix ?? "";
		if (fallbackPrefix) if (fallback.startsWith(fallbackPrefix)) fallback = fallback.slice(fallbackPrefix.length);
		else expandSVGCSSIconSetFallback(iconSet);
		iconData.fallback = fallback;
	}
	iconSet.icons[iconName] = iconData;
	const { classes, animations, statefulClasses, keyframes } = icon;
	const classNames = new Set([...Object.keys(classes || {}), ...Object.keys(statefulClasses || {})]);
	for (const className of classNames) if (!iconSet.classes?.[className]) {
		const classData = {};
		iconSet.classes = iconSet.classes || Object.create(null);
		iconSet.classes[className] = classData;
		const r = classes?.[className];
		if (r) classData.r = minifyRules(r);
		const a = animations?.[className];
		if (a) classData.a = minifyRules(a);
		const statefulClass = statefulClasses?.[className];
		if (statefulClass) {
			const { stateRules, transition, stateTransition } = statefulClass;
			if (stateRules) classData.sr = stringifyObject(stateRules);
			if (transition) classData.t = minifyRules(transition);
			if (stateTransition) classData.st = stringifyObject(stateTransition);
		}
	}
	if (keyframes) {
		iconSet.keyframes = iconSet.keyframes || Object.create(null);
		const iconSetKeyframes = iconSet.keyframes;
		for (const keyframeName in keyframes) if (!iconSetKeyframes[keyframeName]) {
			const value = keyframes[keyframeName];
			iconSetKeyframes[keyframeName] = typeof value === "string" ? value : minifyCSS(stringifyCSSAnimationFrames(value));
		}
	}
}
export { addIconToSVGCSSIconSet };
