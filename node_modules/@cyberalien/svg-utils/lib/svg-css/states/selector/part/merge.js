import { mergeMultipleArrays } from "../helpers/iterate.js";
import { mergeMultipleSelectorSubParts } from "../sub/merge.js";
/**
* Merge all selectors
*
* Returns null if merge is not possible
*
* If multiple results are returned, all have identical at-rules and svg selectors, but different parent selectors.
*/
function mergeSelectorParts(parts) {
	const atRules = [];
	let svgSelector = null;
	for (const item of parts) {
		if (item.at) {
			for (const atRule of item.at) if (!atRules.includes(atRule)) atRules.push(atRule);
		}
		if (item.svg) if (!svgSelector) svgSelector = item.svg;
		else {
			svgSelector = mergeMultipleSelectorSubParts([svgSelector, item.svg]);
			if (!svgSelector) return null;
		}
	}
	const baseResult = {
		at: atRules.length > 0 ? atRules : void 0,
		svg: svgSelector || void 0
	};
	const allParentSelectors = parts.filter((item) => item.parents).map((item) => item.parents);
	const mergedParentSelectors = allParentSelectors.length > 1 ? mergeMultipleArrays(allParentSelectors, (a, b) => mergeMultipleSelectorSubParts([a, b])) : allParentSelectors;
	if (mergedParentSelectors.length) return mergedParentSelectors.map((parents) => ({
		...baseResult,
		parents
	}));
	else return [baseResult];
}
export { mergeSelectorParts };
