import { parseSVGStyle } from "../svg/parse-style.js";
import { animateTags, shapeTags } from "../svg/data/tags.js";
import { tagSpecificPresentationalAttributes } from "../svg/data/attributes.js";
import { analyseSVGStructure } from "../svg/analyse.js";
import { allowDefaultColorValue, defaultBlackColor, defaultColorValues, shapeColorAttributes, specialColorAttributes } from "./attribs.js";
import { colorToString, compareColors, stringToColor } from "@iconify/utils/lib/colors";

/**
* Properties to check
*/
const propsToCheck = Object.keys(defaultColorValues);
const animatePropsToCheck = [
	"from",
	"to",
	"values"
];
/**
* Find colors in icon
*
* Clean up icon before running this function to convert style to attributes using
* cleanupInlineStyle() or cleanupSVG(), otherwise results might be inaccurate
*/
function parseColors(svg, options = {}) {
	const result = {
		colors: [],
		hasUnsetColor: false,
		hasGlobalStyle: false
	};
	const defaultColor = typeof options.defaultColor === "string" ? stringToColor(options.defaultColor) : options.defaultColor;
	/**
	* Find matching color in results
	*/
	function findColor(color, add = false) {
		const isString = typeof color === "string";
		for (let i = 0; i < result.colors.length; i++) {
			const item = result.colors[i];
			if (item === color) return item;
			if (!isString && typeof item !== "string" && compareColors(item, color)) return item;
		}
		if (add) {
			result.colors.push(color);
			return color;
		}
		return null;
	}
	/**
	* Add color to item and to results
	*/
	function addColorToItem(prop, color, item, add = true) {
		const addedColor = findColor(color, add !== false);
		if (item) {
			const itemColors = item._colors || (item._colors = {});
			itemColors[prop] = addedColor === null ? color : addedColor;
		}
	}
	/**
	* Get element color
	*/
	function getElementColor(prop, item, elements) {
		function find(prop) {
			let currentItem = item;
			const allowDefaultColor = allowDefaultColorValue[prop];
			while (currentItem) {
				const element = elements.get(currentItem.index);
				const color = element._colors?.[prop];
				if (color !== void 0) return color;
				if (allowDefaultColor) {
					if (allowDefaultColor === true || element.attribs[allowDefaultColor]) return null;
				}
				currentItem = currentItem.parent;
				if (currentItem?.usedAsMask) return defaultColorValues[prop];
			}
			return defaultColorValues[prop];
		}
		let propColor = find(prop);
		if (propColor !== null && typeof propColor === "object" && propColor.type === "current" && prop !== "color") propColor = find("color");
		return propColor;
	}
	/**
	* Change color
	*/
	function checkColor(prop, value, item) {
		switch (value.trim().toLowerCase()) {
			case "":
			case "inherit": return;
		}
		const parsedColor = stringToColor(value);
		const defaultValue = parsedColor || value;
		if (parsedColor?.type === "function" && parsedColor.func === "url") {
			addColorToItem(prop, defaultValue, item, false);
			return value;
		}
		if (!options.callback) {
			addColorToItem(prop, defaultValue, item);
			return value;
		}
		const callbackResult = options.callback(prop, value, parsedColor, item?.tag, item);
		if (callbackResult instanceof Promise) throw new Error("parseColors does not support async callbacks");
		switch (callbackResult) {
			case "remove": return item ? callbackResult : void 0;
			case "unset": return;
		}
		if (callbackResult === value || parsedColor && callbackResult === parsedColor) {
			addColorToItem(prop, defaultValue, item);
			return value;
		}
		if (typeof callbackResult === "string") {
			addColorToItem(prop, stringToColor(callbackResult) || callbackResult, item);
			return callbackResult;
		}
		const newValue = colorToString(callbackResult);
		addColorToItem(prop, callbackResult, item);
		return newValue;
	}
	parseSVGStyle(svg, (item) => {
		const prop = item.prop;
		const value = item.value;
		if (!propsToCheck.includes(prop)) return value;
		const newValue = checkColor(prop, value);
		if (newValue === void 0) return newValue;
		if (item.type === "global") result.hasGlobalStyle = true;
		return newValue;
	});
	const iconData = analyseSVGStructure(svg, options);
	const { elements, tree } = iconData;
	const removedElements = /* @__PURE__ */ new Set();
	const parsedElements = /* @__PURE__ */ new Set();
	function removeElement(index, element) {
		function removeChildren(element) {
			element.children.forEach((item) => {
				if (item.type !== "tag") return;
				const element = item;
				const index = element._index;
				if (index && !removedElements.has(index)) {
					element._removed = true;
					removedElements.add(index);
					removeChildren(element);
				}
			});
		}
		element._removed = true;
		removedElements.add(index);
		removeChildren(element);
	}
	function parseTreeItem(item) {
		const index = item.index;
		if (removedElements.has(index) || parsedElements.has(index)) return;
		parsedElements.add(index);
		const element = elements.get(index);
		if (element._removed) return;
		const { tag, attribs } = element;
		if (item.parent) {
			const parentIndex = item.parent.index;
			const parentElement = elements.get(parentIndex);
			if (parentElement._colors) element._colors = { ...parentElement._colors };
		}
		for (let i = 0; i < propsToCheck.length; i++) {
			const prop = propsToCheck[i];
			if (prop === "fill" && animateTags.has(tag)) continue;
			const value = attribs[prop];
			if (typeof value === "string") {
				const newValue = checkColor(prop, value, element);
				if (newValue !== value) if (newValue === void 0) {
					delete attribs[prop];
					if (element._colors) delete element._colors[prop];
				} else if (newValue === "remove") {
					removeElement(index, element);
					return;
				} else attribs[prop] = newValue;
			}
		}
		if (animateTags.has(tag)) {
			const attr = attribs.attributeName;
			if (propsToCheck.includes(attr)) for (let i = 0; i < animatePropsToCheck.length; i++) {
				const elementProp = animatePropsToCheck[i];
				const fullValue = attribs[elementProp];
				if (typeof fullValue !== "string") continue;
				const splitValues = fullValue.split(";");
				let updatedValues = false;
				for (let j = 0; j < splitValues.length; j++) {
					const value = splitValues[j];
					if (value !== void 0) {
						const newValue = checkColor(elementProp, value);
						if (newValue !== value) {
							updatedValues = true;
							splitValues[j] = typeof newValue === "string" ? newValue : "";
						}
					}
				}
				if (updatedValues) attribs[elementProp] = splitValues.join(";");
			}
		}
		if (!result.hasGlobalStyle) {
			let requiredProps;
			if (shapeTags.has(tag)) requiredProps = shapeColorAttributes;
			specialColorAttributes.forEach((attr) => {
				if (tagSpecificPresentationalAttributes[tag]?.has(attr)) requiredProps = [attr];
			});
			if (requiredProps) {
				const itemColors = element._colors || (element._colors = {});
				for (let i = 0; i < requiredProps.length; i++) {
					const prop = requiredProps[i];
					if (getElementColor(prop, item, elements) === defaultBlackColor) if (defaultColor) {
						const defaultColorValue = typeof defaultColor === "function" ? defaultColor(prop, element, item, iconData) : defaultColor;
						findColor(defaultColorValue, true);
						attribs[prop] = colorToString(defaultColorValue);
						itemColors[prop] = defaultColorValue;
					} else result.hasUnsetColor = true;
				}
			}
		}
		for (let i = 0; i < item.children.length; i++) {
			const childItem = item.children[i];
			if (!childItem.usedAsMask) parseTreeItem(childItem);
		}
	}
	parseTreeItem(tree);
	function removeElements(node, parent) {
		if (parent) {
			const index = node.index;
			if (removedElements.has(index) || elements.get(index)._removed) {
				parent.children = parent.children.filter((item) => item.index !== index);
				return;
			}
		}
		node.children.forEach((child) => {
			removeElements(child, node);
		});
	}
	removeElements(tree);
	return result;
}
/**
* Check if color is empty, such as 'none' or 'transparent'
*/
function isEmptyColor(color) {
	const type = color.type;
	return type === "none" || type === "transparent";
}

export { isEmptyColor, parseColors };