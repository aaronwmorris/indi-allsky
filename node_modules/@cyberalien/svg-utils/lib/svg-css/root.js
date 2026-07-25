import { iterateXMLContent } from "../xml/iterate.js";
import { createCSSClassName } from "../css/hash.js";
import { toggleClassName } from "../classname/toggle.js";
import { extractSVGTagPropertiesForCSS } from "./props/props.js";
/**
* Convert SVG tags tree to SVG+CSS
*
* Returns used CSS class names with rules
*/
function convertSVGRootToCSS(root, options) {
	const rules = Object.create(null);
	iterateXMLContent(root, (node) => {
		if (node.type === "tag") {
			const props = extractSVGTagPropertiesForCSS(node, options);
			if (props) {
				const className = createCSSClassName(props.rules, options);
				toggleClassName(node.attribs, className, true);
				rules[className] = props.rules;
			}
		}
	});
	return rules;
}
export { convertSVGRootToCSS };
