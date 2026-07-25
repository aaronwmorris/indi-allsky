/**
* Get tag for error message
*/
function analyseTagError(element) {
	let result = "<" + element.tag;
	if (element._id) result += " id=\"" + element._id + "\"";
	const value = element.attribs["d"];
	if (typeof value === "string") result += " d=\"" + (value.length > 16 ? value.slice(0, 12) + "..." : value) + "\"";
	return result + ">";
}

export { analyseTagError };