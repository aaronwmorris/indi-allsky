/**
* Create context item for minification
*/
function createCompactContext() {
	return {
		map: /* @__PURE__ */ new Map(),
		data: []
	};
}
/**
* Minify item
*
* If value is not a string, set it in `actualValue` and string `value` for comparison
*/
function compactItem(context, stringifiedValue, parent, key, actualValue) {
	const { map, data } = context;
	const existing = map.get(stringifiedValue);
	if (typeof existing === "number") {
		parent[key] = existing;
		return;
	}
	const value = actualValue ?? stringifiedValue;
	if (existing) {
		const index = data.length;
		data.push(value);
		map.set(stringifiedValue, index);
		parent[key] = index;
		existing.parent[existing.key] = index;
		return;
	}
	map.set(stringifiedValue, {
		parent,
		key
	});
	parent[key] = value;
}
export { compactItem, createCompactContext };
