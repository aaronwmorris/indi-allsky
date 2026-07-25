import { isBadSVGColor, isSVGColorAttribute } from "../svg/data/colors.js";
import { getTokens } from "./parser/tokens.js";

/**
* Parse inline style
*/
function parseInlineStyle(style) {
	const tokens = getTokens(style);
	if (!(tokens instanceof Array)) return null;
	const results = Object.create(null);
	for (let i = 0; i < tokens.length; i++) {
		const token = tokens[i];
		if (token.type !== "rule") return null;
		if (isSVGColorAttribute(token.prop) && isBadSVGColor(token.value)) continue;
		results[token.prop] = token.value;
	}
	return results;
}

export { parseInlineStyle };