import { parseSVG } from "../parse.js";
import { defsTag } from "../data/tags.js";
import { badAttributePrefixes, badAttributes, badSoftwareAttributes, tagSpecificPresentationalAttributes } from "../data/attributes.js";

/**
* Remove useless attributes
*/
function removeBadAttributes(svg) {
	parseSVG(svg, (item) => {
		const node = item.node;
		const tagName = node.tag;
		const attribs = node.attribs;
		Object.keys(attribs).forEach((attr) => {
			if (attr.slice(0, 2) === "on" || badAttributes.has(attr) || badSoftwareAttributes.has(attr) || badAttributePrefixes.has(attr.split("-").shift())) {
				delete attribs[attr];
				return;
			}
			if (defsTag.has(tagName) && !tagSpecificPresentationalAttributes[tagName].has(attr)) {
				delete attribs[attr];
				return;
			}
			const nsParts = attr.split(":");
			if (nsParts.length > 1) {
				const namespace = nsParts.shift();
				const newAttr = nsParts.join(":");
				switch (namespace) {
					case "xlink":
						if (attribs[newAttr] === void 0) attribs[newAttr] = attribs[attr];
						break;
				}
				delete attribs[attr];
			}
		});
	});
}

export { removeBadAttributes };