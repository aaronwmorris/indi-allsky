import { parseIconFallbackTemplate } from "./parse.js";
const match = /^[a-z0-9:-]*$/;
/**
* Parse and test fallback template string
*
* This will make sure template is valid and does not contain invalid characters
*/
function parseAndTestIconFallbackTemplate(fallback, states) {
	const template = parseIconFallbackTemplate(fallback, states);
	if (template) {
		for (const chunk of template) if (typeof chunk === "string") {
			if (!chunk.match(match)) return;
		} else if ("values" in chunk) {
			if (!chunk.values.every((v) => v.match(match))) return;
		}
	}
	return template;
}
export { parseAndTestIconFallbackTemplate };
