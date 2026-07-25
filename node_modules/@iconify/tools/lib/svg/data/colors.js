/**
* Check for color attribute
*/
function isSVGColorAttribute(prop) {
	return prop === "fill" || prop === "stroke" || prop.endsWith("color");
}
/**
* Check for color that cannot be parsed
*/
function isBadSVGColor(value) {
	return value.startsWith("color(") || value.startsWith("device-color(") || value.startsWith("var(");
}

export { isBadSVGColor, isSVGColorAttribute };