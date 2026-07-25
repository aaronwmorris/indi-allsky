import { stringifyCSSKeyframes, stringifyCSSSelector } from "./stringify.js";
import { mergeCSSRules } from "./rules.js";
import { mergeLegacyCSS } from "./legacy.js";
/**
* Create empty stylesheet
*/
function createEmptyStylesheet() {
	return {
		selectors: Object.create(null),
		keyframes: Object.create(null)
	};
}
/**
* Add generated selector to stylesheet
*/
function addGeneratedSelector(stylesheet, tree, rules) {
	tree = tree.filter((item, index) => item.startsWith("@") ? tree.indexOf(item) === index : true);
	let parent = stylesheet.selectors;
	for (let i = 0; i < tree.length; i++) {
		const selector = tree[i];
		if (!parent[selector]) parent[selector] = {};
		const parentItem = parent[selector];
		if (i === tree.length - 1) {
			parentItem.rules = mergeCSSRules(rules, parentItem.rules);
			return;
		}
		if (!parentItem.nested) parentItem.nested = Object.create(null);
		parent = parentItem.nested;
	}
}
function indent(depth) {
	return "  ".repeat(depth);
}
/**
* Stringify generated selectors to CSS string
*/
function stringifySelectors(data, depth = 0) {
	const lines = [];
	const selectors = Object.keys(data);
	selectors.sort((a, b) => a.startsWith("@") ? b.startsWith("@") ? a.localeCompare(b) : 1 : b.startsWith("@") ? -1 : a.localeCompare(b));
	for (const selector of selectors) {
		const item = data[selector];
		if (item.rules) {
			const value = stringifyCSSSelector(selector, item.rules, depth);
			if (value.length) lines.push(value);
		}
		if (item.nested) {
			const nestedContent = stringifySelectors(item.nested, depth + 1);
			if (nestedContent.length) lines.push(`${indent(depth)}${selector} {\n${nestedContent}${indent(depth)}}\n`);
		}
	}
	return lines.join("\n");
}
/**
* Stringify generated stylesheet to CSS string
*/
function stringifyStylesheet(stylesheet, legacyCSS = false) {
	const lines = [];
	if (legacyCSS) stylesheet = mergeLegacyCSS(stylesheet);
	const selectors = stringifySelectors(stylesheet.selectors);
	if (selectors.length) lines.push(selectors);
	for (const animationName in stylesheet.keyframes) {
		const keyframes = stylesheet.keyframes[animationName];
		const keyframesContent = stringifyCSSKeyframes(animationName, keyframes);
		if (keyframesContent.length) lines.push(keyframesContent);
	}
	return lines.join("\n");
}
export { addGeneratedSelector, createEmptyStylesheet, stringifyStylesheet };
