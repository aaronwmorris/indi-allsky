const firstCSSChars = "abcdefghijklmnopqrstuvwxyz";
const firstIDChars = firstCSSChars + firstCSSChars.toUpperCase();
const numChars = "0123456789";
const allCSSChars = firstCSSChars + numChars + "-_";
const allIDChars = firstIDChars + numChars;
/**
* Convert hash to a string, usable in CSS for class names and keyframes
*/
function hashToString(value, css, hasPrefix = true, limit = 8) {
	const firstChars = css ? firstCSSChars : firstIDChars;
	const chars = css ? allCSSChars : allIDChars;
	const firstLetterRadix = firstChars.length;
	const letterRadix = chars.length;
	const result = [];
	let num = value.shift() ?? 0;
	if (!hasPrefix) {
		result.push(firstChars[num % firstLetterRadix]);
		num = Math.floor(num / firstLetterRadix);
	}
	while (true) {
		while (num < 1) {
			if (!value.length) return result.join("");
			num = value.shift() ?? 0;
		}
		const isLastChar = result.length === limit - 1;
		result.push(isLastChar ? firstChars[num % firstLetterRadix] : chars[num % letterRadix]);
		if (result.length === limit) return result.join("");
		num = Math.floor(num / letterRadix);
	}
}
export { hashToString };
