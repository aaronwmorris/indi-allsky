import { parseXMLContent } from "../xml/parse.js";
import { stringifyXMLContent } from "../xml/stringify.js";
import { convertSVGRootToCSS } from "./root.js";
/**
* Convert SVG content string to SVG+CSS
*/
function convertSVGContentToCSSRules(content, options) {
	const root = parseXMLContent(content);
	if (!root) return { content };
	const classes = convertSVGRootToCSS(root, options);
	if (classes) {
		const newContent = stringifyXMLContent(root, options);
		if (newContent) return {
			content: newContent.trim(),
			classes
		};
	}
	return { content };
}
export { convertSVGContentToCSSRules };
