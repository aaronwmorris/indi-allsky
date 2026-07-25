import { stringifySelectorSubParts } from "../sub/stringify.js";
/**
* Join sub-parts of selector into one string
*/
function joinSubParts(parts) {
	return parts.map((item, index) => {
		const chunk = stringifySelectorSubParts(item);
		return index > 0 && chunk.startsWith("&") ? chunk.replace("&", "").trim() : chunk;
	}).join(" ");
}
/**
* Convert selector parts to array of strings
*
* Assumes that all parts have identical at-rules and svg selectors, but different parent selectors,
* same as returned by mergeSelectorParts()
*/
function stringifySelectorParts(parts) {
	const firstItem = parts[0];
	if (!firstItem) return null;
	const results = [];
	if (firstItem.at) results.push(...firstItem.at);
	if (parts.length > 1) {
		const parentSelectors = /* @__PURE__ */ new Set();
		for (const item of parts) if (item.parents) parentSelectors.add(joinSubParts(item.parents));
		if (parentSelectors.size) results.push(Array.from(parentSelectors).sort((a, b) => a.localeCompare(b)).join(", "));
	} else if (firstItem.parents) results.push(...firstItem.parents.map((item) => stringifySelectorSubParts(item)));
	if (firstItem.svg) results.push(stringifySelectorSubParts(firstItem.svg, true));
	return results;
}
export { stringifySelectorParts };
