import { getUniqueHash } from "../../helpers/hash/unique.js";
import { changeSVGIDs } from "./change.js";
/**
* Create unique IDs for SVG elements
*/
function createUniqueIDs(root, options) {
	changeSVGIDs(root, (id, content) => getUniqueHash(content, {
		css: false,
		prefix: "SVG",
		length: 8,
		...options
	}));
}
export { createUniqueIDs };
