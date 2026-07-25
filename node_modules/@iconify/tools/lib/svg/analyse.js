import { parseSVG } from "./parse.js";
import { defsTag, maskTags, reusableElementsWithPalette, styleTag, useTag } from "./data/tags.js";
import { commonColorPresentationalAttributes, markerAttributes, tagSpecificNonPresentationalAttributes, urlPresentationalAttributes } from "./data/attributes.js";
import { analyseTagError } from "./analyse/error.js";

/**
* Find all IDs, links, which elements use palette, which items aren't used
*
* Before running this function run cleanup functions to change inline style to attributes and fix attributes
*/
function analyseSVGStructure(svg, options = {}) {
	const fixErrors = options.fixErrors;
	let root = svg.$svg;
	if (root._parsed) {
		svg.load(svg.toString());
		root = svg.$svg;
	}
	root._parsed = true;
	const elements = /* @__PURE__ */ new Map();
	const ids = Object.create(null);
	let links = [];
	/**
	* Found element with id
	*/
	function addID(element, id) {
		if (ids[id]) throw new Error(`Duplicate id "${id}"`);
		element._id = id;
		ids[id] = element._index;
		return true;
	}
	/**
	* Add _belongsTo
	*/
	function gotElementWithID(element, id, isMask) {
		addID(element, id);
		if (!element._belongsTo) element._belongsTo = [];
		element._belongsTo.push({
			id,
			isMask,
			indexes: new Set([element._index])
		});
	}
	/**
	* Mark element as reusable, set properties
	*/
	function gotReusableElement(item, isMask) {
		const element = item.node;
		const attribs = element.attribs;
		const index = element._index;
		const id = attribs["id"];
		if (typeof id !== "string") {
			const message = `Definition element ${analyseTagError(element)} does not have id`;
			if (fixErrors) {
				item.removeNode = true;
				item.testChildren = false;
				console.warn(message);
				return false;
			}
			throw new Error(message);
		}
		if (ids[id] && fixErrors) {
			console.warn(`Duplicate id "${id}"`);
			item.removeNode = true;
			item.testChildren = false;
			return false;
		}
		element._reusableElement = {
			id,
			isMask,
			index
		};
		gotElementWithID(element, id, isMask);
		return true;
	}
	/**
	* Found element that uses another element
	*/
	function gotElementReference(item, id, usedAsMask) {
		const element = item.node;
		const link = {
			id,
			usedByIndex: element._index,
			usedAsMask
		};
		links.push(link);
		if (!element._linksTo) element._linksTo = [];
		element._linksTo.push(link);
	}
	let index = 0;
	parseSVG(svg, (item) => {
		const parents = item.parents;
		const element = item.node;
		const tagName = element.tag;
		if (styleTag.has(tagName)) {
			item.testChildren = false;
			return;
		}
		const attribs = element.attribs;
		index++;
		element._index = index;
		elements.set(index, element);
		if (!parents.length) {
			element._usedAsMask = false;
			element._usedAsPaint = true;
			return;
		}
		element._usedAsMask = false;
		element._usedAsPaint = false;
		const parentItem = parents[0];
		const parentElement = parentItem.node;
		if (maskTags.has(tagName)) {
			if (!gotReusableElement(item, true)) return;
		} else if (reusableElementsWithPalette.has(tagName)) {
			if (!gotReusableElement(item, false)) return;
		} else if (defsTag.has(parentItem.node.tag)) {
			if (!gotReusableElement(item, false)) return;
		} else if (!defsTag.has(tagName)) {
			element._usedAsMask = parentElement._usedAsMask;
			element._usedAsPaint = parentElement._usedAsPaint;
			element._parentElement = parentElement._index;
			if (!parentElement._childElements) parentElement._childElements = [];
			parentElement._childElements.push(index);
			const parentReusableElement = parentElement._reusableElement;
			if (parentReusableElement) {
				if (element._reusableElement) throw new Error(`Reusable element ${analyseTagError(element)} is inside another reusable element id="${parentReusableElement.id}"`);
				element._reusableElement = parentReusableElement;
			}
			const parentBelongsTo = parentElement._belongsTo;
			if (parentBelongsTo) {
				const list = element._belongsTo || (element._belongsTo = []);
				parentBelongsTo.forEach((item) => {
					item.indexes.add(index);
					list.push(item);
				});
			}
			if (element._id === void 0) {
				const id = attribs["id"];
				if (typeof id === "string") if (ids[id] && fixErrors) {
					console.warn(`Duplicate id "${id}"`);
					delete attribs["id"];
				} else gotElementWithID(element, id, false);
			}
		}
		if (tagSpecificNonPresentationalAttributes[tagName]?.has("href")) {
			const href = attribs["href"] || attribs["xlink:href"];
			if (typeof href === "string") {
				if (href.slice(0, 1) !== "#") throw new Error(`Invalid link in ${analyseTagError(element)}`);
				gotElementReference(item, href.slice(1), false);
			}
		}
		Object.keys(attribs).forEach((attr) => {
			let value = attribs[attr];
			if (typeof value !== "string") return;
			if (value.slice(0, 5).toLowerCase() !== "url(#") return;
			value = value.slice(5);
			if (value.slice(-1) !== ")") return;
			const id = value.slice(0, value.length - 1).trim();
			if (urlPresentationalAttributes.has(attr)) {
				gotElementReference(item, id, attr !== "filter");
				return;
			}
			if (commonColorPresentationalAttributes.has(attr) || markerAttributes.has(attr)) {
				gotElementReference(item, id, false);
				return;
			}
		});
	});
	links = links.filter((item) => {
		const id = item.id;
		if (ids[id]) return true;
		function fix() {
			const index = item.usedByIndex;
			const element = elements.get(index);
			const tagName = element.tag;
			function remove() {
				const parentIndex = element._parentElement;
				const parent = typeof parentIndex === "number" ? elements.get(parentIndex) : null;
				if (parent) {
					if (parent._childElements) parent._childElements = parent._childElements.filter((num) => num !== index);
					parent._belongsTo?.forEach((list) => {
						list.indexes.delete(index);
					});
					parent.children = parent.children.filter((node) => node !== element);
				}
			}
			if (element._linksTo) element._linksTo = element._linksTo.filter((item) => item.id !== id);
			if (!element.children.length) {
				if (useTag.has(tagName)) {
					remove();
					return;
				}
			}
			const matches = new Set(["#" + id, "url(#" + id + ")"]);
			const attribs = element.attribs;
			for (const attr in attribs) if (matches.has(attribs[attr])) delete attribs[attr];
		}
		const message = `Missing element with id="${id}"`;
		if (fixErrors) {
			fix();
			console.warn(message);
		} else throw new Error(message);
		return false;
	});
	function hasChildItem(tree, child, canThrow) {
		const item = tree.children.find((item) => item.index === child.index && item.usedAsMask === child.usedAsMask);
		if (item && canThrow) throw new Error("Recursion");
		return !!item;
	}
	const tree = {
		index: 1,
		usedAsMask: false,
		children: []
	};
	function parseTreeItem(tree, usedItems, inMask) {
		const element = elements.get(tree.index);
		if (tree.usedAsMask || inMask) {
			element._usedAsMask = true;
			inMask = true;
		} else element._usedAsPaint = true;
		usedItems = usedItems.slice(0);
		usedItems.push(element._index);
		element._childElements?.forEach((childIndex) => {
			if (usedItems.includes(childIndex)) throw new Error("Recursion");
			const childItem = {
				index: childIndex,
				usedAsMask: false,
				children: [],
				parent: tree
			};
			tree.children.push(childItem);
			parseTreeItem(childItem, usedItems, inMask);
		});
		element._linksTo?.forEach((link) => {
			const linkIndex = ids[link.id];
			const usedAsMask = link.usedAsMask;
			const childItem = {
				index: linkIndex,
				usedAsMask,
				children: [],
				parent: tree
			};
			if (hasChildItem(tree, childItem, false)) return;
			tree.children.push(childItem);
			parseTreeItem(childItem, usedItems, inMask || usedAsMask);
		});
	}
	parseTreeItem(tree, [0], false);
	return {
		elements,
		ids,
		links,
		tree
	};
}

export { analyseSVGStructure };