const combinators = new Set([
	">",
	"+",
	"~"
]);
/**
* Split selector into smaller parts
*
* Assuming selector is in format: '.foo[bar="baz"]:hover:active'
* Class name should be before attribute selector, pseudo-classes should be last
*/
function splitSelectorToSubParts(selector) {
	const result = {};
	const firstChar = selector[0];
	if (combinators.has(firstChar)) {
		result.combinator = firstChar;
		selector = selector.slice(1).trim();
	}
	const pseudoMatches = selector.matchAll(/:[a-z-]+(\(:[a-z-]+\))*/g);
	for (const match of pseudoMatches) {
		const value = match[0];
		selector = selector.replace(value, "");
		const list = result.pseudo || /* @__PURE__ */ new Set();
		if (!result.pseudo) result.pseudo = list;
		list.add(value);
	}
	const attrMatches = selector.matchAll(/\[[^\]]+\]/g);
	for (const match of attrMatches) {
		const value = match[0];
		selector = selector.replace(value, "");
		const list = result.attr || /* @__PURE__ */ new Set();
		if (!result.attr) result.attr = list;
		list.add(value);
	}
	const tagMatch = selector.match(/^[a-zA-Z][a-zA-Z0-9-]*/);
	if (tagMatch) {
		result.tag = tagMatch[0];
		selector = selector.slice(result.tag.length);
	}
	const idMatch = selector.match(/^#[a-zA-Z0-9_-]+/);
	if (idMatch) {
		result.id = idMatch[0];
		selector = selector.slice(result.id.length);
	}
	if (selector) {
		const chunks = selector.split(".");
		const list = /* @__PURE__ */ new Set();
		for (let i = 1; i < chunks.length; i++) list.add((i === 1 ? `${chunks[0]}.` : ".") + chunks[i]);
		result.name = list;
	}
	return result;
}
export { combinators, splitSelectorToSubParts };
