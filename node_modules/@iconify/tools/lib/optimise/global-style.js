import { parseSVG } from "../svg/parse.js";
import { isBadSVGColor, isSVGColorAttribute } from "../svg/data/colors.js";
import { parseSVGStyle } from "../svg/parse-style.js";
import { allValidTags, animateTags } from "../svg/data/tags.js";
import { splitClassName } from "@cyberalien/svg-utils";

const tempDataAttrbiute = "data-gstyle-temp";
/**
* Expand global style
*/
function cleanupGlobalStyle(svg) {
	const backup = svg.toString();
	let containsTempAttr = false;
	const animatedClasses = /* @__PURE__ */ new Set();
	parseSVG(svg, (item) => {
		const node = item.node;
		const attribs = node.attribs;
		const tagName = node.tag;
		if (!animateTags.has(tagName)) return;
		if (attribs["attributeName"] !== "class") return;
		[
			"from",
			"to",
			"values"
		].forEach((attr) => {
			const value = attribs[attr];
			if (typeof value !== "string") return;
			value.split(";").forEach((item) => {
				splitClassName(item).forEach((className) => {
					animatedClasses.add(className);
				});
			});
		});
	});
	const removeClasses = /* @__PURE__ */ new Set();
	try {
		parseSVGStyle(svg, (styleItem) => {
			const returnValue = styleItem.value;
			if (styleItem.type !== "global") return returnValue;
			const selectorTokens = styleItem.selectorTokens;
			for (let i = 0; i < selectorTokens.length; i++) if (selectorTokens[i].type !== "selector") return returnValue;
			const selectors = styleItem.selectors;
			const matches = [];
			for (let i = 0; i < selectors.length; i++) {
				const selector = styleItem.selectors[i];
				const firstChar = selector.charAt(0);
				let matchType;
				if (firstChar === ".") matchType = "class";
				else if (firstChar === "#") matchType = "id";
				else if (allValidTags.has(selector)) matchType = "tag";
				else return returnValue;
				const valueMatch = matchType === "tag" ? selector : selector.slice(1);
				if (matchType === "class" && animatedClasses.has(valueMatch)) return returnValue;
				matches.push({
					type: matchType,
					value: valueMatch
				});
			}
			const isMatch = (tagName, node) => {
				const attribs = node.attribs;
				for (let i = 0; i < matches.length; i++) {
					const { type, value } = matches[i];
					switch (type) {
						case "id":
							if (attribs.id === value) return true;
							break;
						case "tag":
							if (tagName === value) return true;
							break;
						case "class": {
							const className = attribs["class"];
							if (typeof className === "string" && splitClassName(className).includes(value)) return true;
						}
					}
				}
				return false;
			};
			parseSVG(svg, (svgItem) => {
				const node = svgItem.node;
				const tagName = node.tag;
				if (!isMatch(tagName, node)) return;
				const attribs = node.attribs;
				const tempDataValue = attribs[tempDataAttrbiute];
				const addedAttributes = new Set(typeof tempDataValue === "string" ? splitClassName(tempDataValue) : []);
				const prop = styleItem.prop;
				if (isSVGColorAttribute(prop) && isBadSVGColor(styleItem.value)) return;
				attribs[prop] = styleItem.value;
				addedAttributes.add(prop);
				attribs[tempDataAttrbiute] = Array.from(addedAttributes).join(" ");
				containsTempAttr = true;
			});
			matches.forEach((match) => {
				if (match.type === "class") removeClasses.add(match.value);
			});
		});
		parseSVG(svg, (svgItem) => {
			const attribs = svgItem.node.attribs;
			const className = attribs["class"];
			const classList = typeof className === "string" ? splitClassName(className) : void 0;
			if (!classList) return;
			const filtered = classList.filter((item) => !removeClasses.has(item));
			if (!filtered.length) delete attribs["class"];
			else attribs["class"] = filtered.join(" ");
		});
		if (containsTempAttr) parseSVG(svg, (item) => {
			delete item.node.attribs[tempDataAttrbiute];
		});
	} catch {
		svg.load(backup);
	}
}

export { cleanupGlobalStyle };