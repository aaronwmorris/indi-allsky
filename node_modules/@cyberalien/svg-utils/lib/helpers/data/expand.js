/**
* Expand minified item
*/
function expandItem(list, parent, key) {
	const index = parent[key];
	if (typeof index === "number" && list[index]) parent[key] = list[index];
}
export { expandItem };
