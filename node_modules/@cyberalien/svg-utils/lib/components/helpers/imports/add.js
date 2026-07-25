function addToSet(set, names) {
	if (Array.isArray(names)) for (const name of names) set.add(name);
	else set.add(names);
}
/**
* Add named import
*/
function addNamedImport(data, source, names) {
	addToSet(data.named[source] ??= /* @__PURE__ */ new Set(), names);
}
/**
* Add type import
*/
function addTypeImport(data, source, types) {
	addToSet(data.types[source] ??= /* @__PURE__ */ new Set(), types);
}
export { addNamedImport, addTypeImport };
