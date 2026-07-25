import { iterateXMLContent } from "../../xml/iterate.js";
/**
* Remove duplicate IDs from SVG
*/
function removeUnusedIDs(root, data) {
	const remove = /* @__PURE__ */ new Set();
	for (const id in data.usage) if (!data.usage[id].length) remove.add(id);
	if (remove.size) return iterateXMLContent(root, (node, stack) => {
		if (node.type !== "tag") return;
		const id = node.attribs.id;
		if (typeof id !== "string" || !remove.has(id)) return;
		switch (node.tag) {
			case "mask":
			case "clipPath":
			case "symbol": return "remove";
		}
		if (stack[stack.length - 1]?.tag === "defs") return "remove";
		delete node.attribs.id;
	});
	return root;
}
export { removeUnusedIDs };
