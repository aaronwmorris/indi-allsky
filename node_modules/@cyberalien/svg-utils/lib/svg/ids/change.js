import { iterateXMLContent } from "../../xml/iterate.js";
import { stringifyXMLContent } from "../../xml/stringify.js";
import { changeIDInString } from "./string.js";
/**
* Change IDs in SVG using a callback function
*/
function changeSVGIDs(root, callback) {
	const idMap = /* @__PURE__ */ new Map();
	const idNodes = /* @__PURE__ */ new Map();
	const nestedIDs = /* @__PURE__ */ new Map();
	const results = {
		map: Object.create(null),
		usage: Object.create(null)
	};
	const usage = [];
	const parse = (replacement) => {
		iterateXMLContent(root, (node, stack) => {
			if (node.type !== "tag") return;
			const attribs = node.attribs;
			const nodeID = attribs.id;
			if (typeof nodeID === "string") {
				if (!replacement) {
					if (idNodes.has(nodeID)) throw new Error(`Duplicate ID found: ${nodeID}`);
					idNodes.set(nodeID, node);
					idMap.set(node, nodeID);
				} else if (nodeID === replacement[0]) {
					const newID = replacement[1];
					attribs.id = newID;
					if (!results.map[newID]) results.map[newID] = [node];
					else results.map[newID].push(node);
				}
			}
			for (const attrib in attribs) {
				const value = attribs[attrib];
				if (typeof value !== "string") continue;
				const add = (id) => {
					usage.push({
						node,
						attrib,
						id
					});
					[node, ...stack].forEach((node) => {
						const parentID = idMap.get(node);
						if (parentID) {
							const nested = nestedIDs.get(parentID) || [];
							if (!nested.includes(id)) {
								nested.push(id);
								nestedIDs.set(parentID, nested);
							}
						}
					});
				};
				switch (attrib) {
					case "id": break;
					case "begin":
					case "end": {
						const newValue = value.split(";").map((part) => {
							const chunks = part.trim().split(".");
							if (chunks.length < 2) return part;
							const time = chunks[1];
							if (time?.startsWith("begin") || time?.startsWith("end")) {
								const id = chunks.shift();
								if (!replacement) add(id);
								else if (id === replacement[0]) return `${replacement[1]}.${chunks.join(".")}`;
							}
							return part;
						}).join(";");
						if (replacement) attribs[attrib] = newValue;
						break;
					}
					case "href":
					case "xlink:href":
						if (value.startsWith("#")) {
							const id = value.slice(1);
							if (!replacement) add(id);
							else if (id === replacement[0]) attribs[attrib] = `#${replacement[1]}`;
						}
						break;
					default: if (value.startsWith("url(#")) {
						const id = value.slice(5, -1);
						if (!replacement) add(id);
						else if (id === replacement[0]) attribs[attrib] = `url(#${replacement[1]})`;
					}
				}
			}
		});
	};
	parse();
	if (!idMap.size) return results;
	const allIDs = new Set(idMap.values());
	const parseIDs = (parseAll = false) => {
		const oldSize = allIDs.size;
		for (const id of allIDs) {
			const nested = nestedIDs.get(id)?.filter((nestedID) => nestedID !== id && allIDs.has(nestedID)) ?? [];
			if (parseAll || !nested.length) {
				const node = idNodes.get(id);
				const content = stringifyXMLContent([node]);
				if (!content) throw new Error(`Failed to stringify node with ID: ${id}`);
				const newID = callback(id, changeIDInString(content, id, "{id}"), node.tag);
				if (newID !== id) parse([id, newID]);
				allIDs.delete(id);
				const idUsage = [];
				for (const item of usage) if (item.id === id) idUsage.push(item.node);
				results.usage[newID] = idUsage;
			}
		}
		return allIDs.size !== oldSize;
	};
	while (allIDs.size) if (!parseIDs()) {
		parseIDs(true);
		return results;
	}
	return results;
}
export { changeSVGIDs };
