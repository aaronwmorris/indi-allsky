import { sortObject } from "../helpers/misc/sort-object.js";
import { getUniqueHash } from "../helpers/hash/unique.js";
/**
* Get class name for CSS rules
*/
function createCSSClassName(rules, options) {
	return getUniqueHash(sortObject(rules), {
		css: true,
		length: 6,
		...options
	});
}
export { createCSSClassName };
