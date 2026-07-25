import { iterateXMLContent } from "@cyberalien/svg-utils";

/**
* Parse SVG
*
* This function finds all elements in SVG and calls callback for each element.
*/
function parseSVG(svg, callback) {
	const map = /* @__PURE__ */ new Map();
	iterateXMLContent([svg.$svg], (node, stack) => {
		if (node.type !== "tag") return;
		const parents = [];
		for (const parent of stack) {
			const parentItem = map.get(parent);
			if (!parentItem.testChildren) return "skip";
			parents.unshift(parentItem);
		}
		const item = {
			svg,
			node,
			parents,
			testChildren: true,
			removeNode: false
		};
		map.set(node, item);
		if (callback(item) instanceof Promise) throw new Error("parseSVG does not support async callbacks");
		if (item.removeNode) return "remove";
		if (!item.testChildren) return "skip";
	});
}

export { parseSVG };