import { maskTags, reusableElementsWithPalette } from "../data/tags.js";
import { badAttributePrefixes, badAttributes, badSoftwareAttributes, commonAttributes, junkSVGAttributes, stylingAttributes, tagSpecificNonPresentationalAttributes, tagSpecificPresentationalAttributes } from "../data/attributes.js";

/**
* Clean up SVG
*/
function cleanupSVGRoot(svg) {
	const root = svg.$svg;
	const tagName = "svg";
	if (root.tag !== tagName) throw new Error(`Unexpected root tag <${root.tag}>`);
	const attribs = root.attribs;
	const moveToChildren = Object.create(null);
	Object.keys(attribs).forEach((attr) => {
		const value = attribs[attr];
		if (commonAttributes.has(attr) || badAttributes.has(attr) || junkSVGAttributes.has(attr) || badSoftwareAttributes.has(attr) || badAttributePrefixes.has(attr.split("-").shift()) || attr.split(":").length > 1) {
			delete attribs[attr];
			return;
		}
		switch (attr) {
			case "width":
			case "height":
				if (typeof value !== "string") return;
				if (value.slice(-2) === "px") {
					const num = value.replace("px", "");
					if (parseFloat(num).toString() === num) attribs[attr] = num;
				}
				return;
		}
		if (tagSpecificNonPresentationalAttributes[tagName]?.has(attr)) return;
		if (tagSpecificPresentationalAttributes[tagName]?.has(attr) && tagSpecificPresentationalAttributes.g.has(attr)) {
			moveToChildren[attr] = value;
			delete attribs[attr];
			return;
		}
		if (stylingAttributes.has(attr)) {
			switch (attr) {
				case "style": return;
				case "class":
					delete attribs[attr];
					return;
			}
			throw new Error(`Unexpected attribute "${attr}" on <${tagName}>`);
		}
		if (attr.slice(0, 2) === "on" || attr.slice(0, 5) === "aria-" || attr.slice(0, 6) === "xmlns:") {
			delete attribs[attr];
			return;
		}
		console.warn(`Removing unexpected attribute on SVG: ${attr}`);
		delete attribs[attr];
	});
	if (Object.keys(moveToChildren).length) {
		const nodesToMove = root.children;
		const wrapper = {
			type: "tag",
			tag: "g",
			attribs: moveToChildren,
			children: []
		};
		root.children = [];
		for (const child of nodesToMove) {
			if (child.type !== "tag") {
				wrapper.children.push(child);
				continue;
			}
			const tagName = child.tag;
			if (tagName === "style" || tagName === "title" || reusableElementsWithPalette.has(tagName) || maskTags.has(tagName)) root.children.push(child);
			else wrapper.children.push(child);
		}
		root.children.push(wrapper);
	}
}

export { cleanupSVGRoot };