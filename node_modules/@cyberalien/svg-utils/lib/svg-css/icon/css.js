import { addGeneratedSelector, createEmptyStylesheet } from "../../css/stylesheet.js";
import { prefersReduceMotion } from "../../helpers/reduce-motion.js";
import { getSelectorsForStateValues } from "../states/selector/parse.js";
/**
* Add styles for stateful icon to stylesheet
*
* If commonStylesheet is an object, all styles will be added to it and result
* will contain the same stylesheet for all classes.
*
* If commonStylesheet is not an object, styles will be separated into different
* stylesheets for classes and keyframes, which can be reused across icons.
*/
function renderStatefulSVGCSSIconStyle(icon, context, commonStylesheet = createEmptyStylesheet) {
	const stylesheets = Object.create(null);
	const getStylesheet = (className) => {
		if (typeof commonStylesheet === "object") return commonStylesheet;
		if (!stylesheets[className]) stylesheets[className] = commonStylesheet(className);
		return stylesheets[className];
	};
	for (const className in icon.classes) addGeneratedSelector(getStylesheet(className), [`.${className}`], icon.classes[className]);
	for (const className in icon.animations) {
		const tree = [prefersReduceMotion];
		if (context?.staticClassname) tree.push(`svg:not(.${context.staticClassname})`);
		addGeneratedSelector(getStylesheet(className), [...tree, `.${className}`], icon.animations[className]);
	}
	for (const keyframeName in icon.keyframes) getStylesheet(keyframeName).keyframes[keyframeName] = icon.keyframes[keyframeName];
	if (context) for (const className in icon.statefulClasses) {
		const baseClassName = `.${className}`;
		const stylesheet = getStylesheet(className);
		const classData = icon.statefulClasses[className];
		if (classData.transition) addGeneratedSelector(getStylesheet(className), [prefersReduceMotion, baseClassName], classData.transition);
		for (const stateKey in classData.stateRules) {
			const selectors = getSelectorsForStateValues(context, stateKey);
			if (selectors) for (const tree of selectors) addGeneratedSelector(stylesheet, [...tree, baseClassName], classData.stateRules[stateKey]);
		}
		for (const stateKey in classData.stateTransition) {
			const selectors = getSelectorsForStateValues(context, stateKey);
			if (selectors) for (const tree of selectors) addGeneratedSelector(stylesheet, [
				prefersReduceMotion,
				...tree,
				baseClassName
			], classData.stateTransition[stateKey]);
		}
	}
	return stylesheets;
}
/**
* Add styles for icon to stylesheet
*
* If commonStylesheet is an object, all styles will be added to it and result
* will contain the same stylesheet for all classes.
*
* If commonStylesheet is not an object, styles will be separated into different
* stylesheets for classes and keyframes, which can be reused across icons.
*/
function renderSVGCSSIconStyle(icon, commonStylesheet) {
	return renderStatefulSVGCSSIconStyle(icon, null, commonStylesheet);
}
export { renderSVGCSSIconStyle, renderStatefulSVGCSSIconStyle };
