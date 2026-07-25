/**
* Simple hashing function, based on https://gist.github.com/jlevy/c246006675becc446360a798e2b2d781
*/
function hashString(str, seed = 0) {
	let h1 = 3735928559 ^ seed, h2 = 1103547991 ^ seed;
	for (let i = 0, ch; i < str.length; i++) {
		ch = str.charCodeAt(i);
		h1 = Math.imul(h1 ^ ch, 2654435761);
		h2 = Math.imul(h2 ^ ch, 1597334677);
	}
	h1 = Math.imul(h1 ^ h1 >>> 16, 2246822507);
	h1 ^= Math.imul(h2 ^ h2 >>> 13, 3266489909);
	h2 = Math.imul(h2 ^ h2 >>> 16, 2246822507);
	h2 ^= Math.imul(h1 ^ h1 >>> 13, 3266489909);
	return [h2 >>> 0, h1 >>> 0];
}
export { hashString };
