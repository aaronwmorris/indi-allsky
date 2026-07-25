import { splitSelectorToParts } from "./part/split.js";
import { stringifySelectorSubParts } from "./sub/stringify.js";
/**
* Split comma separated selectors into parts, group by compatibility so later can be merged
*/
function splitSelectorsForState(selectors) {
	const groups = [];
	const hashMap = /* @__PURE__ */ new Map();
	const list = selectors.split(",").map((s) => s.trim());
	for (const selector of list) {
		const split = splitSelectorToParts(selector);
		if (!split) return null;
		const hash = JSON.stringify({
			at: split.at,
			svg: split.svg ? stringifySelectorSubParts(split.svg, true) : void 0
		});
		const group = hashMap.get(hash);
		if (group) group.push(split);
		else {
			const newGroup = [split];
			hashMap.set(hash, newGroup);
			groups.push(newGroup);
		}
	}
	return groups;
}
export { splitSelectorsForState };
