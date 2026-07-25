/**
* Template for property
*/
const factoryPropTemplate = "{prop}=\"{value}\"";
/**
* Stringify properties for component
*/
function stringifyFactoryProps(props, dynamicTemplate, staticTemplate = factoryPropTemplate, separator = " ") {
	const result = [];
	for (const key in props) {
		const value = props[key];
		const actualValue = typeof value === "string" ? value : value.value;
		if (actualValue !== void 0) {
			const template = typeof value === "string" ? staticTemplate : value.template ?? dynamicTemplate;
			if (template) result.push(template.replace("{prop}", key).replace("{value}", actualValue));
		}
	}
	return result.join(separator);
}
export { factoryPropTemplate, stringifyFactoryProps };
