import { parseSVG } from "../svg/parse.js";
import { defsTag, maskTags, symbolTag } from "../svg/data/tags.js";
import { cleanupInlineStyle } from "../svg/cleanup/inline-style.js";
import { unwrapEmptyGroup } from "./unwrap.js";
import { colorToString, stringToColor } from "@iconify/utils";

/**
* Checks if number is tiny, used to remove bad Figma transformations
*/
function isTinyNumber(value, limit) {
	const num = parseInt(value);
	return !isNaN(num) && Math.abs(num) < limit;
}
/**
* Check node
*
* Returns CheckClipPathResult on success, false on error
*/
function checkClipPathNode(clipNode, expectedWidth, expectedHeight) {
	for (const attr in clipNode.attribs) if (attr !== "id") return false;
	const children = clipNode.children.filter((node) => node.type !== "text");
	if (children.length !== 1) return false;
	const childNode = children[0];
	if (childNode.type !== "tag" || childNode.children.length) return false;
	const attribs = { ...childNode.attribs };
	delete attribs["fill"];
	const fill = childNode.attribs["fill"];
	const colorValue = typeof fill === "string" ? stringToColor(fill) : null;
	const colorString = colorValue ? colorToString(colorValue) : null;
	if (fill && colorString !== "#fff") {
		console.warn("Unxepected fill on clip path:", childNode.attribs["fill"]);
		return false;
	}
	switch (childNode.tag) {
		case "rect": {
			const widthValue = attribs["width"];
			const heightValue = attribs["height"];
			if ((typeof widthValue === "string" ? parseInt(widthValue) : widthValue) !== expectedWidth || (typeof heightValue === "string" ? parseInt(heightValue) : heightValue) !== expectedHeight) {
				console.warn("Invalid size of clip path");
				return false;
			}
			delete attribs["width"];
			delete attribs["height"];
			break;
		}
		default:
			console.warn("Unexpected tag in Figma clip path:", childNode.tag);
			return false;
	}
	Object.keys(attribs).forEach((attr) => {
		const value = attribs[attr];
		if (typeof value !== "string") return;
		switch (attr) {
			case "transform": if (value.startsWith("translate(") && value.endsWith(")")) {
				const translateParts = value.slice(10, -1).split(/\s+/);
				const limit = Math.min(expectedWidth, expectedHeight) / 1e3;
				if (translateParts.length === 2 && isTinyNumber(translateParts[0], limit) && isTinyNumber(translateParts[1], limit)) delete attribs[attr];
			}
		}
	});
	return {
		node: clipNode,
		attribs
	};
}
const urlStart = "url(#";
const urlEnd = ")";
/**
* Does the job
*
* Can mess with SVG because on failure backup will be restored
*/
function remove(svg) {
	unwrapEmptyGroup(svg);
	let content = svg.toString();
	const backup = content;
	if (content.includes("frame-clip-def")) {
		cleanupInlineStyle(svg);
		parseSVG(svg, (item) => {
			const node = item.node;
			const tagName = node.tag;
			const attribs = node.attribs;
			Object.keys(attribs).forEach((attr) => {
				const value = attribs[attr];
				if (typeof value !== "string") return;
				switch (attr) {
					case "id":
						if (!maskTags.has(tagName) && !symbolTag.has(tagName)) delete attribs[attr];
						break;
					case "class":
					case "xmlns:xlink":
					case "version":
						delete attribs[attr];
						break;
					case "transform": {
						const trimmed = value.replace(/\s+/g, "").replace(/\.0+/g, "");
						if (!trimmed || trimmed === "matrix(1,0,0,1,0,0)") delete attribs[attr];
						break;
					}
					case "rx":
					case "ry":
					case "x":
					case "y":
						if (value === "0") delete attribs[attr];
						break;
					case "fill-opacity":
					case "stroke-opacity":
					case "opacity":
						if (value === "1") delete attribs[attr];
						break;
					case "fill":
					case "stroke": {
						const colorValue = stringToColor(value);
						if (colorValue?.type === "rgb") attribs[attr] = colorToString(colorValue);
					}
				}
			});
		});
		content = svg.toString();
	}
	const clipPathBlocks = content.match(/<clipPath[^>]*>[\s\S]+?<\/clipPath>/g);
	if (clipPathBlocks?.length === 2 && clipPathBlocks[0] === clipPathBlocks[1]) {
		const split = clipPathBlocks[0];
		const lines = content.split(split);
		content = lines.shift() + split + lines.join("");
	}
	if (content.includes("<defs>")) content = content.replace(/<\/?defs>/g, "");
	if (content !== backup) svg.load(content);
	const rootNode = svg.$svg;
	const children = rootNode.children.slice(0);
	const shapesToClip = [];
	let clipID;
	for (let i = 0; i < children.length; i++) {
		const node = children[i];
		if (node.type === "tag") {
			const tagName = node.tag;
			if (!defsTag.has(tagName) && !maskTags.has(tagName) && !symbolTag.has(tagName)) {
				const clipPath = node.attribs["clip-path"];
				if (typeof clipPath !== "string" || !clipPath.startsWith(urlStart) || !clipPath.endsWith(urlEnd)) return false;
				const id = clipPath.slice(5, -1);
				if (typeof clipID === "string" && clipID !== id) return false;
				clipID = id;
				shapesToClip.push(node);
			}
		}
	}
	if (typeof clipID !== "string") return false;
	const findClipPath = () => {
		for (let i = 0; i < children.length; i++) {
			const node = children[i];
			if (node.type === "tag" && node.tag === "clipPath") {
				if (node.attribs["id"] === clipID) {
					const result = checkClipPathNode(node, svg.viewBox.width, svg.viewBox.height);
					rootNode.children = rootNode.children.filter((n) => n !== node);
					return result;
				}
				return;
			}
		}
	};
	const clipPath = findClipPath();
	if (!clipPath) return false;
	const attribs = clipPath.attribs;
	for (let i = 0; i < shapesToClip.length; i++) {
		const node = shapesToClip[i];
		delete node.attribs["clip-path"];
		for (const attr in attribs) {
			if (node.attribs[attr] !== void 0) return false;
			node.attribs[attr] = attribs[attr];
		}
	}
	return true;
}
/**
* Removes clip path from SVG, which Figma and Penpot add to icons that might have overflowing elements.
* Also removes mess generated by Penpot
*
* Function was originally designed for Figma only, but later added support for Penpot
*/
function removeFigmaClipPathFromSVG(svg) {
	const backup = svg.toString();
	try {
		if (remove(svg)) return true;
	} catch {}
	svg.load(backup);
	return false;
}

export { removeFigmaClipPathFromSVG };