/**
* Stringify properties for component
*/
function parse(props, format) {
	const result = [];
	for (const key in props) {
		const value = props[key];
		if (typeof value !== "string" && value.type) result.push(format(key, value));
	}
	return result;
}
/**
* Stringify properties for component
*/
function stringifyFactoryPropTypes(props) {
	return parse(props, (key, value) => {
		return `\t${key}${value.required ? "" : "?"}: ${value.type};`;
	}).join("\n");
}
/**
* Get used properties
*/
function getUsedFactoryProps(props) {
	return parse(props, (key) => key);
}
export { getUsedFactoryProps, stringifyFactoryPropTypes };
