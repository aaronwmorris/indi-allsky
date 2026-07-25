import { addGeneratedSelector, createEmptyStylesheet } from "./stylesheet.js";
function isMediaQuery(selector) {
	return selector.startsWith("@");
}
function splitSelector(selector) {
	return selector.split(",").map((part) => part.trim());
}
function mergeSelectors(list1, list2) {
	if (!list1.length) return list2;
	if (!list2.length) return list1;
	const newList = [];
	for (const item1 of list1) for (const item2 of list2) newList.push(item1 + " " + item2);
	return newList;
}
/**
* Merge selectors for backwards compatibility with legacy CSS structure: no nested CSS
*/
function mergeLegacyCSS(stylesheet) {
	const mergedStylesheet = createEmptyStylesheet();
	mergedStylesheet.keyframes = stylesheet.keyframes;
	function add(selector, media, parent) {
		if (selector.rules) {
			const tree = [...media];
			if (parent.length) tree.push(parent.join(", "));
			addGeneratedSelector(mergedStylesheet, tree, selector.rules);
		}
		if (selector.nested) for (const nestedSelector in selector.nested) {
			const isMedia = isMediaQuery(nestedSelector);
			add(selector.nested[nestedSelector], isMedia ? [...media, nestedSelector] : media, isMedia ? parent : mergeSelectors(parent, splitSelector(nestedSelector)));
		}
	}
	for (const selector in stylesheet.selectors) {
		const isMedia = isMediaQuery(selector);
		add(stylesheet.selectors[selector], isMedia ? [selector] : [], isMedia ? [] : splitSelector(selector));
	}
	return mergedStylesheet;
}
export { mergeLegacyCSS };
