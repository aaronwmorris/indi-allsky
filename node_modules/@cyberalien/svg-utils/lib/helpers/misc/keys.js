import { sortObject } from "./sort-object.js";
/**
* Compare keys, return true on match
*/
function compareKeys(key1, key2) {
	if (key1 === key2) return true;
	if (typeof key1 !== "object" || typeof key2 !== "object" || !key1 || !key2) return false;
	return JSON.stringify(sortObject(key1)) === JSON.stringify(sortObject(key2));
}
export { compareKeys };
