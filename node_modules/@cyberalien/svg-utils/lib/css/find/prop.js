/**
* Find all values of a CSS property in content
*/
function findCSSPropertyValues(content, property) {
	const values = [];
	content.matchAll(new RegExp(`${property}\\s*:\\s*([^;]+);`, "g")).forEach((match) => {
		values.push(...match[1].split(",").map((part) => part.trim()));
	});
	return values;
}
export { findCSSPropertyValues };
