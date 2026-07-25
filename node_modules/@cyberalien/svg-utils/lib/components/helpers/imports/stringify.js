/**
* Split relative and absolute imports
*/
function split(imports, relative) {
	function isRelative(path) {
		return path.startsWith(".") || path.startsWith("~") || path.startsWith("@/") || path.startsWith("virtual:");
	}
	function shouldInclude(path) {
		return isRelative(path) === relative;
	}
	function filterObject(data) {
		return Object.fromEntries(Object.entries(data).filter(([key]) => shouldInclude(key)));
	}
	return {
		default: filterObject(imports.default),
		named: filterObject(imports.named),
		types: filterObject(imports.types),
		full: new Set([...imports.full].filter(shouldInclude)),
		css: new Set([...imports.css].filter(shouldInclude))
	};
}
/**
* Export imports as string
*/
function stringifyFactoryImports(imports, includeTypes = true) {
	const lines = [];
	for (const isRelative of [false, true]) {
		const data = split(imports, isRelative);
		for (const source of data.full) lines.push(`import '${source}';`);
		for (const source in data.default) lines.push(`import ${data.default[source]} from '${source}';`);
		for (const source in data.named) {
			const items = [...data.named[source]].sort().join(", ");
			if (items) lines.push(`import { ${items} } from '${source}';`);
		}
		if (includeTypes) for (const source in data.types) {
			const items = [...data.types[source]].sort().join(", ");
			if (items) lines.push(`import type { ${items} } from '${source}';`);
		}
		for (const source of data.css) lines.push(`import '${source}';`);
	}
	if (lines.length) lines.push("");
	return lines.join("\n");
}
export { stringifyFactoryImports };
