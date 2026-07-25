import { splitSelectorToSubParts } from "../sub/split.js";
const charAfterAtRule = [
	".",
	"&",
	":",
	"[",
	"#",
	"*"
];
/**
* Create selector parts from given parameters
*
* Should be used when selector is hard to parse from string, such as:
* - `@media (max-width: 600px) label:focus &` -> parser will not be able to tell if "label" is part of at-rule or parent selector
*/
function createSelectorParts(atRules, parentSelectors, svgSelector) {
	return {
		at: atRules ? atRules : void 0,
		parents: parentSelectors ? Array.isArray(parentSelectors) ? parentSelectors.map(splitSelectorToSubParts) : [splitSelectorToSubParts(parentSelectors)] : void 0,
		svg: svgSelector ? splitSelectorToSubParts(svgSelector) : void 0
	};
}
/**
* Split selector into parts
*/
function splitSelectorToParts(selector) {
	selector = selector.replace(/[\s]+/g, " ").trim();
	const result = {};
	if (selector.startsWith("@")) {
		const chunks = selector.split(" ");
		const atRule = [chunks.shift()];
		let isAtRuleComplete = false;
		while (chunks.length > 0) {
			const firstChar = chunks[0][0];
			if (charAfterAtRule.includes(firstChar)) {
				isAtRuleComplete = true;
				break;
			}
			atRule.push(chunks.shift());
		}
		if (!isAtRuleComplete) return { at: [selector] };
		result.at = [atRule.join(" ")];
		selector = chunks.join(" ");
	}
	selector = selector.replace(/\s*([>+~])\s*/g, " $1").trim();
	const parents = [];
	const chunks = selector.split(" ");
	while (chunks.length > 0) {
		const nextChunk = chunks.shift();
		if (nextChunk.includes("&")) {
			if (chunks.length) return null;
			result.svg = splitSelectorToSubParts(nextChunk.replace("&", ""));
		} else parents.push(splitSelectorToSubParts(nextChunk));
	}
	if (parents.length) result.parents = parents;
	return result;
}
export { createSelectorParts, splitSelectorToParts };
