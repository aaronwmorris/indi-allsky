import { stringifyXMLContent } from "@cyberalien/svg-utils";

/**
* Removes empty group from SVG root element
*/
function unwrapEmptyGroup(svg) {
	const root = svg.$svg;
	if (root.children.length !== 1) return;
	const groupNode = root.children[0];
	if (groupNode.type !== "tag" || groupNode.tag !== "g" || !groupNode.children.length) return;
	const html = stringifyXMLContent(groupNode.children);
	for (const attr in groupNode.attribs) {
		const value = groupNode.attribs[attr];
		if (typeof value !== "string") continue;
		switch (attr) {
			case "id":
				if (html?.includes(value)) return;
				break;
			default: return;
		}
	}
	root.children = groupNode.children;
}

export { unwrapEmptyGroup };