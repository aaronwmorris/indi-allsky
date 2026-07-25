import { iterateXMLContent } from "../../xml/iterate.js";
/**
* Remove duplicate IDs from SVG
*/
function removeDuplicateIDs(root, data) {
	const remove = /* @__PURE__ */ new Set();
	for (const id in data.map) if (data.map[id].length > 1) remove.add(id);
	if (remove.size) {
		const removing = /* @__PURE__ */ new Set();
		return iterateXMLContent(root, (node) => {
			if (node.type !== "tag") return;
			const id = node.attribs.id;
			if (typeof id !== "string" || !remove.has(id)) return;
			if (removing.has(id)) return "remove";
			removing.add(id);
		});
	}
	return root;
}
export { removeDuplicateIDs };
