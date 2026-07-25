import { sortObject } from "../misc/sort-object.js";
import { hashToString } from "./stringify.js";
import { hashString } from "./hash.js";
/**
* Hash an object, make sure hash is unique
*
* Number of unique hashes per length, with prefix for CSS:
* 6 chars = 2b unique hashes
* 7 chars = 78b unique hashes <-- got collision here
* 8 chars = 2.9t unique hashes
* 9 chars = 113t unique hashes
*
* Numer of unique hashes per length, with prefix for ID:
* 6 chars = 47b unique hashes
* 7 chars = 2.9t unique hashes
* 8 chars = 183t unique hashes
*/
function getUniqueHash(data, options) {
	const { length, lengths, css, context } = options;
	const prefix = options.prefix || "";
	const str = typeof data === "string" ? data : JSON.stringify(sortObject(data));
	const hasPrefix = !!prefix;
	const values = hashString(str);
	let hash = hashToString(values, css, hasPrefix, typeof length === "function" ? length(str) : length);
	if (lengths?.[hash]) hash = hashToString(values, css, hasPrefix, lengths[hash]);
	if (!context.cache) context.cache = Object.create(null);
	const cache = context.cache;
	const result = `${prefix}${hash}`;
	if (!cache[result]) cache[result] = str;
	else if (cache[result] !== str) {
		const msg = `Hash collision detected: ${hash}`;
		if (options.throwOnCollision) throw new Error(msg);
		else console.warn(msg);
	}
	return result;
}
export { getUniqueHash };
