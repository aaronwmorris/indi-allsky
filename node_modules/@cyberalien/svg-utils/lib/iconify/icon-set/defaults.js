const defaultProps = [
	"width",
	"height",
	"left",
	"top"
];
/**
* Get default properties from icon set
*/
function getIconifyIconSetDefaults(data) {
	const defaultValues = {};
	for (const prop of defaultProps) {
		const defaultValue = data[prop];
		if (defaultValue) defaultValues[prop] = defaultValue;
	}
	return defaultValues;
}
export { getIconifyIconSetDefaults };
