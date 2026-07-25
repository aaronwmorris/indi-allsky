import { parseSVG } from "../parse.js";
import { parseInlineStyle } from "../../css/parse.js";
import { badAttributePrefixes, badAttributes, badSoftwareAttributes, insideClipPathAttributes, tagSpecificAnimatedAttributes, tagSpecificInlineStyles, tagSpecificNonPresentationalAttributes, tagSpecificPresentationalAttributes } from "../data/attributes.js";

/**
* Allowed rules
*
* Contains full rules + partial rules.
* Partial rule = first part of rule split by '-' + '*'
*/
const allowedStyleRules = new Set([
	"animation",
	"animation*",
	"offset",
	"offset*",
	"transform",
	"transform*",
	"translate",
	"transition",
	"transition*"
]);
/**
* Known ignored rules, exported by junk software
*
* Full or partial (see above)
*
* Checked after tag specific attributes, so list contains some valid attributes, but when used in wrong place
*/
const knownIgnoredRules = new Set([
	"solid*",
	"paint*",
	"shape*",
	"color-interpolation-filters",
	"stop-opacity"
]);
/**
* Expand inline style
*/
function cleanupInlineStyle(svg) {
	parseSVG(svg, (item) => {
		const node = item.node;
		const tagName = node.tag;
		const attribs = node.attribs;
		if (attribs.style && typeof attribs.style === "string") {
			const parsedStyle = parseInlineStyle(attribs.style);
			if (parsedStyle === null) delete attribs.style;
			else {
				const newStyle = Object.create(null);
				const checkRule = (prop, value) => {
					function warn() {
						console.warn(`Removing unexpected style on "${tagName}": ${prop}`);
					}
					if (badAttributes.has(prop) || tagSpecificNonPresentationalAttributes[tagName]?.has(prop)) return;
					if (tagSpecificAnimatedAttributes[tagName]?.has(prop) || tagSpecificPresentationalAttributes[tagName]?.has(prop)) {
						attribs[prop] = value;
						return;
					}
					const partial = prop.split("-").shift() + "*";
					if (tagSpecificInlineStyles[tagName]?.has(prop) || allowedStyleRules.has(prop) || allowedStyleRules.has(partial)) {
						newStyle[prop] = value;
						return;
					}
					if (insideClipPathAttributes.has(prop)) {
						if (item.parents.find((item) => item.node.tag === "clipPath")) attribs[prop] = value;
						return;
					}
					if (badSoftwareAttributes.has(prop) || badAttributePrefixes.has(prop.split("-").shift()) || knownIgnoredRules.has(prop) || knownIgnoredRules.has(partial)) return;
					if (prop.slice(0, 1) === "-") return;
					warn();
				};
				for (const prop in parsedStyle) checkRule(prop, parsedStyle[prop]);
				const newStyleStr = Object.keys(newStyle).map((key) => key + ":" + newStyle[key] + ";").join("");
				if (newStyleStr.length) attribs.style = newStyleStr;
				else delete attribs.style;
			}
		}
	});
}

export { cleanupInlineStyle };