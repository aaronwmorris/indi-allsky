import { iterateXMLContent } from "../../xml/iterate.js";
import { convertSVGPropertyToCSS } from "./convert.js";
import { svgAnimateTransformTag, svgAnimationTag } from "./tags.js";
/**
* Extract SVG tag properties that can be converted to CSS
*
* Returns CSS rules, does not add a class to tag, but does remove properties from tag
*/
function extractSVGTagPropertiesForCSS(tag, options = {}) {
	const result = {
		props: [],
		rules: Object.create(null)
	};
	const animatedProps = /* @__PURE__ */ new Set();
	iterateXMLContent(tag.children, (node) => {
		if (node.type === "tag") switch (node.tag) {
			case "set":
			case svgAnimationTag: {
				const prop = node.attribs.attributeName;
				if (typeof prop === "string") animatedProps.add(prop);
				break;
			}
			case svgAnimateTransformTag:
				animatedProps.add("transform");
				break;
		}
	});
	for (const prop in tag.attribs) if (!animatedProps.has(prop)) {
		const value = tag.attribs[prop];
		const converted = convertSVGPropertyToCSS(tag.tag, prop, value, options);
		if (converted) {
			const [propName, propValue] = converted;
			result.props.push(propName);
			result.rules[propName] = propValue;
			delete tag.attribs[prop];
		}
	}
	return result.props.length > 0 ? result : void 0;
}
export { extractSVGTagPropertiesForCSS };
