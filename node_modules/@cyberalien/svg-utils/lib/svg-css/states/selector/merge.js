import { mergeSelectorParts } from "./part/merge.js";
/**
* Merge sets of StateSelectorData into one
*/
function mergeSelectorsForStates(data) {
	const groupedResults = Object.create(null);
	const next = (parents, key, index) => {
		if (index >= data.length) {
			const merged = mergeSelectorParts(parents);
			if (!merged) return false;
			if (!groupedResults[key]) groupedResults[key] = [];
			groupedResults[key].push(...merged);
			return true;
		}
		const group = data[index];
		if (!group.length) return false;
		for (let i = 0; i < group.length; i++) {
			const items = group[i];
			const nextKey = `${key}:${i}`;
			for (const item of items) if (!next([...parents, item], nextKey, index + 1)) return false;
		}
		return true;
	};
	if (!next([], "", 0)) return null;
	return Object.values(groupedResults);
}
export { mergeSelectorsForStates };
